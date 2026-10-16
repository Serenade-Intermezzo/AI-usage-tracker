import {
  buildChartPoints,
  calculateModelEfficiency,
  calculateProjection,
  type HistoryKeys
} from './analytics.js';
import type { UsageStore } from './db.js';
import type {
  AccountSummary,
  DashboardOverview,
  ProviderId,
  RateLimitWindow,
  SyncOverview
} from './types.js';
import { calculateThreadUsageEstimates, calculateWindowBreakdown } from './windows.js';

export interface CurrentLimits {
  fiveHour: RateLimitWindow | null;
  sevenDay: RateLimitWindow | null;
  other: RateLimitWindow[];
}

export interface OverviewInputs {
  provider: ProviderId;
  localOnly?: boolean;
  store: UsageStore;
  limits: CurrentLimits;
  /** Restrict history queries to these sample keys (see HistoryKeys). */
  historyKeys?: HistoryKeys;
  connection: DashboardOverview['connection'];
  account: AccountSummary;
  cloudTasks: DashboardOverview['cloudTasks'];
  sync: SyncOverview;
  notices: string[];
  /** Notice shown when the store holds no session data at all. */
  emptyThreadsNotice: string;
}

/**
 * Assemble the dashboard payload from a provider's store and live state. Every
 * provider shares this so the projections, attribution, and charts behave the
 * same way regardless of where the samples and logs came from. On the central
 * server the store holds every device's events, so every figure below is the
 * combined picture.
 */
export function buildProviderOverview(inputs: OverviewInputs): DashboardOverview {
  const { store, limits, historyKeys = {} } = inputs;
  const localOnly = inputs.localOnly === true;
  const fiveHour = localOnly ? null : limits.fiveHour;
  const sevenDay = localOnly ? null : limits.sevenDay;
  const context = { settledThrough: inputs.sync.settledThrough };
  const fiveHistory = localOnly ? [] : fiveHour
    ? store.getRateLimitHistory(300, fiveHour.resetsAt, 2, historyKeys.fiveHour)
    : store.getRateLimitHistory(300, undefined, 8, historyKeys.fiveHour);
  const sevenHistory = localOnly ? [] : sevenDay
    ? store.getRateLimitHistory(10_080, sevenDay.resetsAt, 8, historyKeys.sevenDay)
    : store.getRateLimitHistory(10_080, undefined, 15, historyKeys.sevenDay);
  const fiveProjection = calculateProjection(fiveHour, fiveHistory);
  const sevenProjection = calculateProjection(sevenDay, sevenHistory);
  const usageEstimates = localOnly ? new Map() : calculateThreadUsageEstimates(store, fiveHour, sevenDay, historyKeys);
  const threads = store.getThreadSummaries(120).map((thread) => ({
    ...thread,
    usage: usageEstimates.get(thread.threadId) ?? { fiveHour: null, sevenDay: null }
  }));
  const totals = store.getTokenTotals();
  const notices = [...inputs.notices];
  if (threads.length === 0) notices.push(inputs.emptyThreadsNotice);

  return {
    provider: inputs.provider,
    trackingScope: localOnly ? 'local' : 'account',
    generatedAt: Math.floor(Date.now() / 1000),
    connection: localOnly ? { connected: true, authType: null, planType: null, error: null } : inputs.connection,
    account: localOnly ? { planType: null, resetCreditsAvailable: null, lifetimeTokens: totals.totalTokens, peakDailyTokens: null, longestRunningTurnSec: null, currentStreakDays: null, longestStreakDays: null, statsSource: 'local', extraUsage: null } : inputs.account,
    limits: {
      fiveHour,
      sevenDay,
      other: localOnly ? [] : limits.other,
      fiveHourStatus: fiveHour ? 'available' : 'not-reported'
    },
    projections: {
      fiveHour: fiveProjection,
      sevenDay: sevenProjection
    },
    histories: {
      fiveHour: buildChartPoints(fiveHour, fiveHistory, fiveProjection),
      sevenDay: buildChartPoints(sevenDay, sevenHistory, sevenProjection)
    },
    breakdown: {
      fiveHour: localOnly ? null : calculateWindowBreakdown(store, fiveHour, 2, historyKeys.fiveHour, context),
      sevenDay: localOnly ? null : calculateWindowBreakdown(store, sevenDay, 9, historyKeys.sevenDay, context)
    },
    accountDailyUsage: localOnly ? [] : store.getAccountDailyUsage(14),
    localDailyUsage: store.getLocalDailyUsage(14),
    hourlyActivity: store.getHourlyActivity(30),
    totals,
    threads,
    modelEfficiency: localOnly ? [] : calculateModelEfficiency(store, historyKeys),
    modelUsage: store.getModelUsageSummaries(),
    cloudTasks: localOnly ? { status: 'disabled', checkedAt: null, tasks: [] } : inputs.cloudTasks,
    sync: inputs.sync,
    notices
  };
}
