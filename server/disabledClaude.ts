import type { Provider } from './providers.js';
/** Disabled without constructing a database or accessing Claude credentials/logs. */
export function createDisabledClaudeProvider(): Provider {
  const disabled = () => {throw new Error('Claude Code is disabled in this installation');};
  return {
    id:'claude', label:'Claude Code', enabled:false,
    get store() {return disabled();},
    start() {}, stop() {}, async refresh() {}, overview:disabled,
    health:() => ({connected:false,error:null}), windows:() => [], windowDetail:() => null,
    scannedThrough:() => null, watching:() => false
  };
}
