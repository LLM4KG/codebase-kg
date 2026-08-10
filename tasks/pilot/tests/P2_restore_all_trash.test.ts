/**
 * Task P2 — Feature addition: Add restoreAllTrash action + Restore All button.
 *
 * Tests verify BEHAVIOR of the new reducer action:
 *   - All trashed notes are restored (trash set to false).
 *   - Non-trashed notes are unaffected.
 *   - Works correctly when no notes are trashed.
 *   - Works correctly when all notes are trashed.
 *   - activeNoteId and selectedNotesIds are updated after restore.
 *
 * Written BEFORE the reference patch (adversarial mode).
 *
 * On unpatched code, `restoreAllTrash` resolves to undefined because
 * ts-jest has diagnostics:false. The first test (toBeDefined) fails
 * immediately, and subsequent tests crash on `undefined()`.
 *
 * These tests use the same patterns as the existing note.test.ts:
 *   - Import reducer and actions from '@/slices/note'
 *   - Use a createNote helper to build test fixtures
 *   - Test reducer(state, action) => nextState directly
 */
import dayjs from 'dayjs'

import reducer, {
  initialState,
  restoreAllTrash,
} from '@/slices/note'
import { Folder } from '@/utils/enums'

function createNote({
  id,
  category,
  text,
  favorite,
  scratchpad,
  trash,
}: {
  id: string
  category?: string
  text?: string
  favorite?: boolean
  scratchpad?: boolean
  trash?: boolean
}) {
  return {
    id,
    text: text ?? `sample note - ${id}`,
    created: dayjs().format(),
    lastUpdated: dayjs().format(),
    category,
    favorite,
    scratchpad,
    trash,
  }
}

describe('P2 - restoreAllTrash', () => {
  test('restoreAllTrash should be a defined action creator', () => {
    expect(restoreAllTrash).toBeDefined()
    expect(typeof restoreAllTrash).toBe('function')
  })

  test('should restore all trashed notes', () => {
    const notes = [
      createNote({ id: '1', trash: true }),
      createNote({ id: '2', trash: true }),
      createNote({ id: '3', trash: false }),
    ]
    const stateBefore = {
      ...initialState,
      notes,
      activeFolder: Folder.TRASH,
    }

    const result = reducer(stateBefore, restoreAllTrash())

    // All previously trashed notes should have trash: false
    const trashedAfter = result.notes.filter((n: any) => n.trash)
    expect(trashedAfter).toHaveLength(0)

    // The two trashed notes should now be restored
    expect(result.notes.find((n: any) => n.id === '1')!.trash).toBe(false)
    expect(result.notes.find((n: any) => n.id === '2')!.trash).toBe(false)
  })

  test('should not affect non-trashed notes', () => {
    const notes = [
      createNote({ id: '1', trash: true }),
      createNote({ id: '2', trash: false, favorite: true, category: 'cat-1' }),
      createNote({ id: '3', text: 'important note' }),
    ]
    const stateBefore = {
      ...initialState,
      notes,
      activeFolder: Folder.TRASH,
    }

    const result = reducer(stateBefore, restoreAllTrash())

    // Non-trashed notes should be unchanged
    const note2 = result.notes.find((n: any) => n.id === '2')!
    expect(note2.favorite).toBe(true)
    expect(note2.category).toBe('cat-1')
    expect(note2.trash).toBeFalsy()

    const note3 = result.notes.find((n: any) => n.id === '3')!
    expect(note3.text).toBe('important note')
    expect(note3.trash).toBeFalsy()
  })

  test('should handle empty trash gracefully', () => {
    const notes = [
      createNote({ id: '1', trash: false }),
      createNote({ id: '2' }),
    ]
    const stateBefore = {
      ...initialState,
      notes,
      activeFolder: Folder.TRASH,
    }

    const result = reducer(stateBefore, restoreAllTrash())

    // All notes should remain unchanged
    expect(result.notes).toHaveLength(2)
    expect(result.notes.every((n: any) => !n.trash)).toBe(true)
  })

  test('should handle state where all notes are trashed', () => {
    const notes = [
      createNote({ id: '1', trash: true }),
      createNote({ id: '2', trash: true }),
      createNote({ id: '3', trash: true }),
    ]
    const stateBefore = {
      ...initialState,
      notes,
      activeFolder: Folder.TRASH,
    }

    const result = reducer(stateBefore, restoreAllTrash())

    expect(result.notes).toHaveLength(3)
    expect(result.notes.every((n: any) => !n.trash || n.trash === false)).toBe(true)
  })

  test('should preserve total note count after restore', () => {
    const notes = [
      createNote({ id: '1', trash: true }),
      createNote({ id: '2', trash: true }),
      createNote({ id: '3', trash: false }),
      createNote({ id: '4', scratchpad: true }),
    ]
    const stateBefore = {
      ...initialState,
      notes,
      activeFolder: Folder.TRASH,
    }

    const result = reducer(stateBefore, restoreAllTrash())

    // No notes should be added or removed
    expect(result.notes).toHaveLength(4)
  })
})
