/**
 * Task P3 — Refactoring: Extract useCopyToClipboard hook from NoteMenuBar.
 *
 * Tests verify the BEHAVIOR of the extracted hook:
 *   - The module exports a function named useCopyToClipboard.
 *   - The hook returns { copiedText, handleCopy }.
 *   - copiedText is initially empty.
 *   - After handleCopy is called, copiedText shows the success message.
 *   - After the timeout, copiedText resets to empty.
 *
 * Written BEFORE the reference patch (adversarial mode).
 *
 * The hook only uses useState and useEffect — no Redux Provider needed.
 * We use a minimal test component rendered via @testing-library/react.
 *
 * Valid alternative solutions:
 *   - Hook in hooks.ts instead of its own file (test imports by module path)
 *   - Different parameter names/order, as long as behavior matches
 *   - Using useCallback internally — doesn't affect observable behavior
 */
import React from 'react'
import { render, fireEvent, act, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'

// This import will fail (module not found) on unpatched code
import { useCopyToClipboard } from '@/utils/useCopyToClipboard'

// Mock the copyToClipboard utility so we don't need real clipboard API
jest.mock('@/utils/helpers', () => ({
  ...(jest.requireActual('@/utils/helpers') as object),
  copyToClipboard: jest.fn(),
}))

/**
 * Minimal test component that exercises the hook.
 * Uses a short timeout (100ms) so tests don't wait 3 seconds.
 */
const TestHarness: React.FC = () => {
  const { copiedText, handleCopy } = useCopyToClipboard('Copied!', 100)

  return (
    <div>
      <span data-testid="copied-text">{copiedText}</span>
      <button data-testid="copy-btn" onClick={() => handleCopy('some-text')}>
        Copy
      </button>
    </div>
  )
}

describe('P3 - useCopyToClipboard hook', () => {
  beforeEach(() => {
    jest.useFakeTimers()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  test('useCopyToClipboard should be a defined export', () => {
    expect(useCopyToClipboard).toBeDefined()
    expect(typeof useCopyToClipboard).toBe('function')
  })

  test('copiedText should be empty initially', () => {
    const { getByTestId } = render(<TestHarness />)
    expect(getByTestId('copied-text').textContent).toBe('')
  })

  test('copiedText should show success message after handleCopy is called', () => {
    const { getByTestId } = render(<TestHarness />)

    act(() => {
      fireEvent.click(getByTestId('copy-btn'))
    })

    expect(getByTestId('copied-text').textContent).toBe('Copied!')
  })

  test('copiedText should reset to empty after timeout', async () => {
    const { getByTestId } = render(<TestHarness />)

    act(() => {
      fireEvent.click(getByTestId('copy-btn'))
    })

    expect(getByTestId('copied-text').textContent).toBe('Copied!')

    // Advance timers past the timeout
    act(() => {
      jest.advanceTimersByTime(150)
    })

    expect(getByTestId('copied-text').textContent).toBe('')
  })

  test('should handle multiple rapid copies without breaking', () => {
    const { getByTestId } = render(<TestHarness />)

    // Click copy multiple times rapidly
    act(() => {
      fireEvent.click(getByTestId('copy-btn'))
    })
    act(() => {
      fireEvent.click(getByTestId('copy-btn'))
    })

    // Should still show the message
    expect(getByTestId('copied-text').textContent).toBe('Copied!')

    // After timeout, should clear
    act(() => {
      jest.advanceTimersByTime(150)
    })

    expect(getByTestId('copied-text').textContent).toBe('')
  })
})
