import { pollDelayForState, TERMINAL_JOB_STATES } from './useJobPolling';

describe('bounded job polling policy', () => {
  test.each([
    ['accepted', 3000],
    ['queued', 3000],
    ['starting', 2000],
    ['running', 2000],
    ['cancelling', 2000],
    [null, 5000],
  ] as const)('uses the accepted visible interval for %s', (state, expected) => {
    expect(pollDelayForState(state, 0, false)).toBe(expected);
  });
  test('backs off retry failures with a bounded ceiling', () => {
    expect(pollDelayForState('running', 2, false)).toBe(8000);
    expect(pollDelayForState('running', 99, false)).toBe(15000);
  });
  test('reduces polling while the document is hidden', () => {
    expect(pollDelayForState('running', 0, true)).toBe(10000);
  });
  test('recognizes every accepted terminal state', () => {
    expect([...TERMINAL_JOB_STATES]).toEqual([
      'cancelled',
      'completed',
      'completed_with_warnings',
      'failed',
      'partially_completed',
      'evicted',
    ]);
  });
});
