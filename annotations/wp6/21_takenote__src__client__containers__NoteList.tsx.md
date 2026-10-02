# WP6 annotation — takenote · `src/client/containers/NoteList.tsx`

<!-- wp6 v1 project=takenote path=src/client/containers/NoteList.tsx sha=e0eddbb9a21ae4cf4c4c7c183f29cfd666e08331 graph=graph_export/takenote/full_dump.cypherl prompt_set=72ef9f041851 -->

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
  1  import React, { useEffect, useRef, useState } from 'react'
  2  import { useDispatch, useSelector } from 'react-redux'
  3  import { MoreHorizontal, Book, Star, Folder as FolderIcon } from 'react-feather'
  4  
  5  import { TestID } from '@resources/TestID'
  6  import { Folder, Shortcuts, ContextMenuEnum } from '@/utils/enums'
  7  import { NoteListButton } from '@/components/NoteList/NoteListButton'
  8  import { SearchBar } from '@/components/NoteList/SearchBar'
  9  import { ContextMenu } from '@/containers/ContextMenu'
 10  import { getNoteTitle, shouldOpenContextMenu, debounceEvent, isDraftNote } from '@/utils/helpers'
 11  import { useKey } from '@/utils/hooks'
 12  import {
 13    permanentlyEmptyTrash,
 14    pruneNotes,
 15    updateActiveNote,
 16    searchNotes,
 17    updateSelectedNotes,
 18  } from '@/slices/note'
 19  import { NoteItem, ReactDragEvent, ReactMouseEvent } from '@/types'
 20  import { getNotes, getSettings, getCategories } from '@/selectors'
 21  import { getNotesSorter } from '@/utils/notesSortStrategies'
 22  
 23  export const NoteList: React.FC = () => {
 24    // ===========================================================================
 25    // Selectors
 26    // ===========================================================================
 27  
 28    const { notesSortKey } = useSelector(getSettings)
 29    const { activeCategoryId, activeFolder, selectedNotesIds, notes, searchValue } =
 30      useSelector(getNotes)
 31    const { categories } = useSelector(getCategories)
 32  
 33    // ===========================================================================
 34    // Dispatch
 35    // ===========================================================================
 36  
 37    const dispatch = useDispatch()
 38  
 39    const _updateSelectedNotes = (noteId: string, multiSelect: boolean) =>
 40      dispatch(updateSelectedNotes({ noteId, multiSelect }))
 41    const _permanentlyEmptyTrash = () => dispatch(permanentlyEmptyTrash())
 42    const _pruneNotes = () => dispatch(pruneNotes())
 43    const _updateActiveNote = (noteId: string, multiSelect: boolean) =>
 44      dispatch(updateActiveNote({ noteId, multiSelect }))
 45    const _searchNotes = debounceEvent(
 46      (searchValue: string) => dispatch(searchNotes(searchValue)),
 47      100
 48    )
 49  
 50    // ===========================================================================
 51    // Refs
 52    // ===========================================================================
 53  
 54    const contextMenuRef = useRef<HTMLDivElement>(null)
 55    const searchRef = React.useRef() as React.MutableRefObject<HTMLInputElement>
 56  
 57    // ===========================================================================
 58    // State
 59    // ===========================================================================
 60  
 61    const [optionsId, setOptionsId] = useState('')
 62    const [optionsPosition, setOptionsPosition] = useState({ x: 0, y: 0 })
 63  
 64    const re = new RegExp(searchValue.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i')
 65    const isMatch = (result: NoteItem) => re.test(result.text)
 66  
 67    const filter: Record<Folder, (note: NoteItem) => boolean> = {
 68      [Folder.CATEGORY]: (note) => !note.trash && note.category === activeCategoryId,
 69      [Folder.SCRATCHPAD]: (note) => !!note.scratchpad,
 70      [Folder.FAVORITES]: (note) => !note.trash && !!note.favorite,
 71      [Folder.TRASH]: (note) => !!note.trash,
 72      [Folder.ALL]: (note) => !note.trash && !note.scratchpad,
 73    }
 74  
 75    const filteredNotes: NoteItem[] = notes
 76      .filter(filter[activeFolder])
 77      .filter(isMatch)
 78      .sort(getNotesSorter(notesSortKey))
 79  
 80    // ===========================================================================
 81    // Handlers
 82    // ===========================================================================
 83  
 84    const focusSearchHandler = () => searchRef.current.focus()
 85  
 86    const handleDragStart = (event: ReactDragEvent, noteId: string = '') => {
 87      event.stopPropagation()
 88  
 89      event.dataTransfer.setData('text/plain', noteId)
 90    }
 91  
 92    const handleNoteOptionsClick = (event: ReactMouseEvent, noteId: string = '') => {
 93      const clicked = event.target
 94  
 95      // Make sure we aren't getting any null values. Any element clicked should be a sub-class of element
 96      if (!clicked) return
 97  
 98      // Ensure the clicked target is supposed to open the context menu
 99      if (shouldOpenContextMenu(clicked as Element)) {
100        // note: don't check for MouseEvent because Cypress MouseEvent !== Window.MouseEvent
101        if ('pageX' in event && 'pageY' in event) {
102          setOptionsPosition({ x: event.pageX, y: event.pageY })
103        }
104      }
105  
106      event.stopPropagation()
107  
108      if (!contextMenuRef.current || !contextMenuRef.current.contains(clicked as HTMLDivElement)) {
109        setOptionsId(!optionsId || optionsId !== noteId ? noteId : '')
110      }
111    }
112  
113    const handleNoteRightClick = (
114      event: React.MouseEvent<HTMLDivElement, MouseEvent>,
115      noteId: string = ''
116    ) => {
117      event.preventDefault()
118      const clicked = event.target
119      const RIGHT_CLICK = 2
120  
121      // Make sure we aren't getting any null values .. any element clicked should be a sub-class of element
122      if (!clicked) return
123  
124      // FIXME: This feels hacky
125      if (event.ctrlKey) return
126  
127      // Make sure we are not right clicking on the menu
128      if (optionsId && event.button == RIGHT_CLICK) return
129  
130      if ('clientX' in event && 'clientY' in event) {
131        setOptionsPosition({ x: event.clientX, y: event.clientY })
132      }
133  
134      event.stopPropagation()
135  
136      if (!contextMenuRef.current || contextMenuRef.current.contains(clicked as HTMLDivElement)) {
137        setOptionsId(!optionsId || optionsId !== noteId ? noteId : '')
138      }
139    }
140  
141    const showEmptyTrash = activeFolder === Folder.TRASH && filteredNotes.length > 0
142  
143    // ===========================================================================
144    // Hooks
145    // ===========================================================================
146  
147    useEffect(() => {
148      document.addEventListener('mousedown', handleNoteOptionsClick)
149  
150      return () => {
151        document.removeEventListener('mousedown', handleNoteOptionsClick)
152      }
153    })
154  
155    useKey(Shortcuts.SEARCH, () => focusSearchHandler())
156  
157    return (
158      <aside className="note-sidebar">
159        <div className="note-sidebar-header">
160          <SearchBar searchRef={searchRef} searchNotes={_searchNotes} />
161          {showEmptyTrash && (
162            <NoteListButton
163              dataTestID={TestID.EMPTY_TRASH_BUTTON}
164              label="Empty"
165              handler={() => _permanentlyEmptyTrash()}
166            >
167              Empty Trash
168            </NoteListButton>
169          )}
170        </div>
171        <div data-testid={TestID.NOTE_LIST} className="note-list">
172          {filteredNotes.map((note: NoteItem, index: number) => {
173            let noteTitle: string | React.ReactElement = getNoteTitle(note.text)
174            const noteCategory = categories.find((category) => category.id === note.category)
175  
176            if (searchValue) {
177              const highlightStart = noteTitle.search(re)
178  
179              if (highlightStart !== -1) {
180                const highlightEnd = highlightStart + searchValue.length
181  
182                noteTitle = (
183                  <>
184                    {noteTitle.slice(0, highlightStart)}
185                    <strong className="highlighted">
186                      {noteTitle.slice(highlightStart, highlightEnd)}
187                    </strong>
188                    {noteTitle.slice(highlightEnd)}
189                  </>
190                )
191              }
192            }
193  
194            return (
195              <div
196                data-testid={TestID.NOTE_LIST_ITEM + index}
197                className={
198                  selectedNotesIds.includes(note.id) ? 'note-list-each selected' : 'note-list-each'
199                }
200                key={note.id}
201                onClick={(event) => {
202                  event.stopPropagation()
203  
204                  _updateSelectedNotes(note.id, event.metaKey)
205                  _updateActiveNote(note.id, event.metaKey)
206                  _pruneNotes()
207                }}
208                onContextMenu={(event) => handleNoteRightClick(event, note.id)}
209                draggable={note.text !== ''}
210                onDragStart={(event) => handleDragStart(event, note.id)}
211              >
212                <div className="note-list-outer">
213                  <div data-testid={'note-title-' + index} className="note-title">
214                    {note.favorite ? (
215                      <>
216                        <div className="icon">
217                          <Star aria-hidden="true" className="note-favorite" size={12} />
218                          <span className="sr-only">Favorite note</span>
219                        </div>
220                        <div className="truncate-text">{noteTitle}</div>
221                      </>
222                    ) : (
223                      <>
224                        <div className="icon" />
225                        <div className="truncate-text"> {noteTitle}</div>
226                      </>
227                    )}
228                  </div>
229                  {!isDraftNote(note) ? (
230                    <div
231                      // TODO: make testID based off of index when we add that to a NoteItem object
232                      data-testid={TestID.NOTE_OPTIONS_DIV + index}
233                      className={optionsId === note.id ? 'note-options selected' : 'note-options'}
234                      onClick={(event) => handleNoteOptionsClick(event, note.id)}
235                    >
236                      <MoreHorizontal aria-hidden="true" size={15} className="context-menu-action" />
237                      <span className="sr-only">Note options</span>
238                    </div>
239                  ) : (
240                    <div className="note-options">&nbsp;</div>
241                  )}
242                </div>
243                {(activeFolder === Folder.ALL || activeFolder === Folder.FAVORITES) && (
244                  <div className="note-category">
245                    {!!noteCategory ? (
246                      <>
247                        <FolderIcon size={12} className="context-menu-action" />
248                        {noteCategory?.name}
249                      </>
250                    ) : (
251                      <>
252                        <Book size={12} className="context-menu-action" />
253                        Notes
254                      </>
255                    )}
256                  </div>
257                )}
258                {optionsId === note.id && !isDraftNote(note) && (
259                  <ContextMenu
260                    contextMenuRef={contextMenuRef}
261                    item={note}
262                    optionsPosition={optionsPosition}
263                    setOptionsId={setOptionsId}
264                    type={ContextMenuEnum.NOTE}
265                  />
266                )}
267              </div>
268            )
269          })}
270        </div>
271      </aside>
272    )
273  }
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (7)

- [y] N Function_Component:NoteList
- [y] N State_Variable:NoteList::optionsId
- [y] N State_Variable:NoteList::optionsPosition
- [n] N EventHandler:NoteList::handleDragStart # cause: llm: JSX binds an inline onDragStart arrow that calls this helper.
- [n] N EventHandler:NoteList::handleNoteOptionsClick # cause: llm: not directly bound as a JSX handler; used via inline callback / addEventListener
- [n] N EventHandler:NoteList::handleNoteRightClick # cause: llm: JSX binds an inline onContextMenu arrow that calls this helper.
- [y] N EventHandler:NoteList::inline_onClick

### LLM-extracted edges (26)

- [y] E DECLARES_STATE Function_Component:NoteList -> State_Variable:NoteList::optionsId
- [y] E DECLARES_STATE Function_Component:NoteList -> State_Variable:NoteList::optionsPosition
- [y] E DEFINED_IN Function_Component:NoteList -> File
- [n] E HAS_HANDLER Function_Component:NoteList -> EventHandler:NoteList::handleDragStart # cause: llm: wrong handler identity; JSX binding is inline_onDragStart.
- [n] E HAS_HANDLER Function_Component:NoteList -> EventHandler:NoteList::handleNoteOptionsClick # cause: llm: helper is not directly bound to a JSX event attribute.
- [n] E HAS_HANDLER Function_Component:NoteList -> EventHandler:NoteList::handleNoteRightClick # cause: llm: wrong handler identity; JSX binding is inline_onContextMenu
- [y] E HAS_HANDLER Function_Component:NoteList -> EventHandler:NoteList::inline_onClick
- [y] E PASSES_PROP Function_Component:NoteList -> Function_Component:ContextMenu@src/client/containers/ContextMenu.tsx prop=contextMenuRef
- [y] E PASSES_PROP Function_Component:NoteList -> Function_Component:ContextMenu@src/client/containers/ContextMenu.tsx prop=item
- [y] E PASSES_PROP Function_Component:NoteList -> Function_Component:ContextMenu@src/client/containers/ContextMenu.tsx prop=optionsPosition
- [y] E PASSES_PROP Function_Component:NoteList -> Function_Component:ContextMenu@src/client/containers/ContextMenu.tsx prop=setOptionsId
- [y] E PASSES_PROP Function_Component:NoteList -> Function_Component:ContextMenu@src/client/containers/ContextMenu.tsx prop=type
- [y] E PASSES_PROP Function_Component:NoteList -> Function_Component:NoteListButton@src/client/components/NoteList/NoteListButton.tsx prop=dataTestID
- [y] E PASSES_PROP Function_Component:NoteList -> Function_Component:NoteListButton@src/client/components/NoteList/NoteListButton.tsx prop=handler
- [y] E PASSES_PROP Function_Component:NoteList -> Function_Component:NoteListButton@src/client/components/NoteList/NoteListButton.tsx prop=label
- [y] E PASSES_PROP Function_Component:NoteList -> Function_Component:SearchBar@src/client/components/NoteList/SearchBar.tsx prop=searchNotes
- [y] E PASSES_PROP Function_Component:NoteList -> Function_Component:SearchBar@src/client/components/NoteList/SearchBar.tsx prop=searchRef
- [y] E USES_COMPONENT Function_Component:NoteList -> Function_Component:ContextMenu@src/client/containers/ContextMenu.tsx
- [y] E USES_COMPONENT Function_Component:NoteList -> Function_Component:NoteListButton@src/client/components/NoteList/NoteListButton.tsx
- [y] E USES_COMPONENT Function_Component:NoteList -> Function_Component:SearchBar@src/client/components/NoteList/SearchBar.tsx
- [y] E USES_CUSTOM_HOOK Function_Component:NoteList -> Custom_Hook:useKey@src/client/utils/hooks.ts
- [y] E USES_LIBRARY_HOOK Function_Component:NoteList -> Library_Hook:useDispatch@react-redux
- [y] E USES_LIBRARY_HOOK Function_Component:NoteList -> Library_Hook:useEffect@react
- [y] E USES_LIBRARY_HOOK Function_Component:NoteList -> Library_Hook:useRef@react
- [y] E USES_LIBRARY_HOOK Function_Component:NoteList -> Library_Hook:useSelector@react-redux
- [y] E USES_LIBRARY_HOOK Function_Component:NoteList -> Library_Hook:useState@react

### Deterministic (sanity scope) (7)

- [y] N File
- [y] E BELONGS_TO File -> Project:takenote
- [y] E PROVIDED_BY Library_Hook:useDispatch@react-redux -> Library:react-redux
- [y] E PROVIDED_BY Library_Hook:useEffect@react -> Library:react
- [y] E PROVIDED_BY Library_Hook:useRef@react -> Library:react
- [y] E PROVIDED_BY Library_Hook:useSelector@react-redux -> Library:react-redux
- [y] E PROVIDED_BY Library_Hook:useState@react -> Library:react

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->
N EventHandler:NoteList::inline_onClick_2 # cause: llm: line 234 
N EventHandler:NoteList::inline_onContextMenu # cause: llm 
N EventHandler:NoteList::inline_onDragStart # cause: llm 
E HAS_HANDLER Function_Component:NoteList -> EventHandler:NoteList::inline_onClick_2 # cause: llm 
E HAS_HANDLER Function_Component:NoteList -> EventHandler:NoteList::inline_onContextMenu # cause: llm 
E HAS_HANDLER Function_Component:NoteList -> EventHandler:NoteList::inline_onDragStart # cause: llm
<!-- wp6:missed-end -->
