import { RefreshCw } from 'lucide-react';
import { BrandLogo } from './BrandLogo';
import { DeviceStatusMenu } from './DeviceStatus';
import { clock, sentence } from '../format';
import type { ProviderCopy } from '../providers';
import type { ProviderId, ProviderInfo, SyncOverview } from '../types';

export type Section = 'overview' | 'reports' | 'chats' | 'models' | 'cloud';

const NAV: Array<{ id: Section; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'reports', label: '周报与月报' },
  { id: 'chats', label: 'Chats' },
  { id: 'models', label: 'Models' },
  { id: 'cloud', label: 'Cloud' }
];

interface TopbarProps {
  localOnly?: boolean;
  active: Section;
  onNavigate: (section: Section) => void;
  provider: ProviderId;
  providers: ProviderInfo[];
  onProviderChange: (provider: ProviderId) => void;
  copy: ProviderCopy;
  connected: boolean;
  planType: string | null;
  updatedAt: number;
  refreshing: boolean;
  onRefresh: () => void;
  sync: SyncOverview | undefined;
  now: number;
}

export function Topbar({
  localOnly = false,
  active,
  onNavigate,
  provider,
  providers,
  onProviderChange,
  copy,
  connected,
  planType,
  updatedAt,
  refreshing,
  onRefresh,
  sync,
  now
}: TopbarProps) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="topbar-brand">
          <a className="wordmark" href="#overview" onClick={(event) => { event.preventDefault(); onNavigate('overview'); }}>
            <BrandLogo />
            <span>{localOnly ? 'Codex 用量统计' : copy.appName}</span>
          </a>
          <div hidden={localOnly} className="segmented provider-switch" role="group" aria-label="Provider">
            {providers.filter(item => item.enabled).map((item) => (
              <button
                key={item.id}
                type="button"
                className={item.id === provider ? 'active' : ''}
                aria-pressed={item.id === provider}
                disabled={!item.enabled}
                title={item.enabled ? `Show ${item.label} usage` : 'Turned off in .env'}
                onClick={() => onProviderChange(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <nav className="topnav" aria-label="Sections">
          {NAV.filter((item) => localOnly ? item.id !== 'cloud' : item.id !== 'reports').map((item) => (
            <button
              key={item.id}
              type="button"
              className={item.id === active ? 'active' : ''}
              aria-current={item.id === active ? 'page' : undefined}
              onClick={() => onNavigate(item.id)}
            >
              {localOnly ? ({overview: '总览', reports: '周报与月报', chats: '聊天明细', models: '模型', cloud: '云任务'}[item.id]) : item.label}
            </button>
          ))}
        </nav>

        <div className="topbar-status">
          {sync ? <DeviceStatusMenu sync={sync} now={now} /> : null}
          <span className={`status-pill ${connected ? 'online' : 'offline'}`}>
            <i aria-hidden="true" />
            {localOnly ? (connected ? '当前账号 · 本机' : '等待当前账号登录') : connected ? (planType ? `${sentence(planType)} plan` : 'Connected') : copy.offline}
          </span>
          <span className="updated-at">Updated {clock(updatedAt)}</span>
          <button
            type="button"
            className="icon-button"
            aria-label="Refresh usage data"
            title="Refresh"
            onClick={onRefresh}
            disabled={refreshing}
          >
            <RefreshCw size={15} strokeWidth={1.75} className={refreshing ? 'spin' : ''} />
          </button>
        </div>
      </div>
    </header>
  );
}
