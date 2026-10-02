# WP6 annotation — takenote · `src/client/containers/KeyboardShortcuts.tsx`

<!-- wp6 v1 project=takenote path=src/client/containers/KeyboardShortcuts.tsx sha=e0eddbb9a21ae4cf4c4c7c183f29cfd666e08331 graph=graph_export/takenote/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator: annotator_1

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `e0eddbb`:

````tsx
  1  import React from 'react'
  2  import { useDispatch, useSelector } from 'react-redux'
  3  import prettier from 'prettier/standalone'
  4  import parserMarkdown from 'prettier/parser-markdown'
  5  
  6  import { useTempState } from '@/contexts/TempStateContext'
  7  import { Folder, Shortcuts } from '@/utils/enums'
  8  import { downloadNotes, getActiveNote, newNoteHandlerHelper } from '@/utils/helpers'
  9  import { useKey } from '@/utils/hooks'
 10  import {
 11    addNote,
 12    swapFolder,
 13    toggleTrashNotes,
 14    updateActiveNote,
 15    updateSelectedNotes,
 16    updateNote,
 17  } from '@/slices/note'
 18  import { sync } from '@/slices/sync'
 19  import { getCategories, getNotes, getSettings } from '@/selectors'
 20  import { CategoryItem, NoteItem } from '@/types'
 21  import { toggleDarkTheme, togglePreviewMarkdown, updateCodeMirrorOption } from '@/slices/settings'
 22  
 23  export const KeyboardShortcuts: React.FC = () => {
 24    // ===========================================================================
 25    // Selectors
 26    // ===========================================================================
 27  
 28    const { categories } = useSelector(getCategories)
 29    const { activeCategoryId, activeFolder, activeNoteId, notes, selectedNotesIds } = useSelector(
 30      getNotes
 31    )
 32    const { darkTheme, previewMarkdown } = useSelector(getSettings)
 33  
 34    const activeNote = getActiveNote(notes, activeNoteId)
 35  
 36    // ===========================================================================
 37    // Dispatch
 38    // ===========================================================================
 39  
 40    const dispatch = useDispatch()
 41  
 42    const _addNote = (note: NoteItem) => dispatch(addNote(note))
 43    const _updateActiveNote = (noteId: string, multiSelect: boolean) =>
 44      dispatch(updateActiveNote({ noteId, multiSelect }))
 45    const _updateSelectedNotes = (noteId: string, multiSelect: boolean) =>
 46      dispatch(updateSelectedNotes({ noteId, multiSelect }))
 47    const _swapFolder = (folder: Folder) => dispatch(swapFolder({ folder }))
 48    const _toggleTrashNotes = (noteId: string) => dispatch(toggleTrashNotes(noteId))
 49    const _sync = (notes: NoteItem[], categories: CategoryItem[]) =>
 50      dispatch(sync({ notes, categories }))
 51    const _togglePreviewMarkdown = () => dispatch(togglePreviewMarkdown())
 52    const _toggleDarkTheme = () => dispatch(toggleDarkTheme())
 53    const _updateCodeMirrorOption = (key: string, value: string) =>
 54      dispatch(updateCodeMirrorOption({ key, value }))
 55  
 56    // ===========================================================================
 57    // State
 58    // ===========================================================================
 59  
 60    const { addingTempCategory, setAddingTempCategory } = useTempState()
 61  
 62    // ===========================================================================
 63    // Handlers
 64    // ===========================================================================
 65  
 66    const newNoteHandler = () =>
 67      newNoteHandlerHelper(
 68        activeFolder,
 69        previewMarkdown,
 70        activeNote,
 71        activeCategoryId,
 72        _swapFolder,
 73        _togglePreviewMarkdown,
 74        _addNote,
 75        _updateActiveNote,
 76        _updateSelectedNotes
 77      )
 78    const newTempCategoryHandler = () => !addingTempCategory && setAddingTempCategory(true)
 79    const trashNoteHandler = () => _toggleTrashNotes(activeNote!.id)
 80    const syncNotesHandler = () => _sync(notes, categories)
 81    const downloadNotesHandler = () => {
 82      if (!activeNote || selectedNotesIds.length === 0) return
 83      downloadNotes(
 84        selectedNotesIds.includes(activeNote.id)
 85          ? notes.filter((note) => selectedNotesIds.includes(note.id))
 86          : [activeNote],
 87        categories
 88      )
 89    }
 90    const togglePreviewMarkdownHandler = () => _togglePreviewMarkdown()
 91    const toggleDarkThemeHandler = () => {
 92      _toggleDarkTheme()
 93      _updateCodeMirrorOption('theme', darkTheme ? 'base16-light' : 'new-moon')
 94    }
 95    const prettifyNoteHandler = () => {
 96      // format current note with prettier
 97      if (activeNote && activeNote.text) {
 98        const formattedText = prettier.format(activeNote.text, {
 99          parser: 'markdown',
100          plugins: [parserMarkdown],
101        })
102  
103        const updatedNote = {
104          ...activeNote,
105          text: formattedText,
106        }
107  
108        dispatch(updateNote(updatedNote))
109      }
110    }
111  
112    // ===========================================================================
113    // Hooks
114    // ===========================================================================
115  
116    useKey(Shortcuts.NEW_NOTE, () => newNoteHandler())
117    useKey(Shortcuts.NEW_CATEGORY, () => newTempCategoryHandler())
118    useKey(Shortcuts.DELETE_NOTE, () => trashNoteHandler())
119    useKey(Shortcuts.SYNC_NOTES, () => syncNotesHandler())
120    useKey(Shortcuts.DOWNLOAD_NOTES, () => downloadNotesHandler())
121    useKey(Shortcuts.PREVIEW, () => togglePreviewMarkdownHandler())
122    useKey(Shortcuts.TOGGLE_THEME, () => toggleDarkThemeHandler())
123    useKey(Shortcuts.PRETTIFY, () => prettifyNoteHandler())
124  
125    return null
126  }
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (1)

- [y] N Function_Component:KeyboardShortcuts

### LLM-extracted edges (6)

- [n] E CONSUMES_CONTEXT Function_Component:KeyboardShortcuts -> Context:TempStateContext@src/client/contexts/TempStateContext.tsx # cause: llm: context use is indirect through useTempState; CONSUMES_CONTEXT is direct-only
- [y] E DEFINED_IN Function_Component:KeyboardShortcuts -> File
- [y] E USES_CUSTOM_HOOK Function_Component:KeyboardShortcuts -> Custom_Hook:useKey@src/client/utils/hooks.ts
- [y] E USES_CUSTOM_HOOK Function_Component:KeyboardShortcuts -> Custom_Hook:useTempState@src/client/contexts/TempStateContext.tsx
- [y] E USES_LIBRARY_HOOK Function_Component:KeyboardShortcuts -> Library_Hook:useDispatch@react-redux
- [y] E USES_LIBRARY_HOOK Function_Component:KeyboardShortcuts -> Library_Hook:useSelector@react-redux

### Deterministic (sanity scope) (4)

- [y] N File
- [y] E BELONGS_TO File -> Project:takenote
- [y] E PROVIDED_BY Library_Hook:useDispatch@react-redux -> Library:react-redux
- [y] E PROVIDED_BY Library_Hook:useSelector@react-redux -> Library:react-redux

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->

<!-- wp6:missed-end -->
