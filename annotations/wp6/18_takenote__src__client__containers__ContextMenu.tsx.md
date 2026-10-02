# WP6 annotation — takenote · `src/client/containers/ContextMenu.tsx`

<!-- wp6 v1 project=takenote path=src/client/containers/ContextMenu.tsx sha=e0eddbb9a21ae4cf4c4c7c183f29cfd666e08331 graph=graph_export/takenote/full_dump.cypherl prompt_set=72ef9f041851 -->

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
  1  import ReactDOM from 'react-dom'
  2  import React, { useEffect, useState, createContext } from 'react'
  3  import { useDispatch, useSelector } from 'react-redux'
  4  
  5  import { SelectCategory } from '@/components/NoteList/SelectCategory'
  6  import { ContextMenuOptions } from '@/containers/ContextMenuOptions'
  7  import { addCategoryToNote, updateActiveCategoryId, updateActiveNote } from '@/slices/note'
  8  import { NoteItem, CategoryItem } from '@/types'
  9  import { getNotes, getCategories, getSettings } from '@/selectors'
 10  import { ContextMenuEnum } from '@/utils/enums'
 11  import { isDraftNote } from '@/utils/helpers'
 12  
 13  export const MenuUtilitiesContext = createContext({
 14    setOptionsId: (id: string) => {},
 15  })
 16  interface Position {
 17    x: number
 18    y: number
 19  }
 20  
 21  export interface ContextMenuProps {
 22    item: NoteItem | CategoryItem
 23    optionsPosition: Position
 24    contextMenuRef: React.RefObject<HTMLDivElement> | null
 25    setOptionsId: (id: string) => void
 26    type: ContextMenuEnum
 27  }
 28  
 29  export const ContextMenu: React.FC<ContextMenuProps> = ({
 30    item,
 31    optionsPosition,
 32    contextMenuRef,
 33    setOptionsId,
 34    type,
 35  }) => {
 36    // ===========================================================================
 37    // Selectors
 38    // ===========================================================================
 39  
 40    const { darkTheme } = useSelector(getSettings)
 41  
 42    // ===========================================================================
 43    // State
 44    // ===========================================================================
 45  
 46    const [elementDimensions, setElementDimensions] = useState<{
 47      offsetHeight: number | null
 48      offsetWidth: number | null
 49    }>({ offsetHeight: null, offsetWidth: null })
 50  
 51    // ===========================================================================
 52    // Hooks
 53    // ===========================================================================
 54  
 55    useEffect(() => {
 56      if (contextMenuRef?.current) {
 57        const { offsetHeight, offsetWidth } = contextMenuRef.current
 58        setElementDimensions({ offsetHeight, offsetWidth })
 59      }
 60    }, [contextMenuRef])
 61  
 62    // ===========================================================================
 63    // Other
 64    // ===========================================================================
 65  
 66    const contextValues = {
 67      setOptionsId,
 68    }
 69  
 70    const getOptionsYPosition = (): Number => {
 71      if (elementDimensions.offsetHeight || elementDimensions.offsetWidth) {
 72        // get the max window frame
 73        const MaxY = window.innerHeight
 74        const optionsSize = elementDimensions.offsetHeight as number
 75  
 76        // if window position - noteOptions position isn't bigger than options, flip it.
 77        return MaxY - optionsPosition.y > optionsSize
 78          ? optionsPosition.y
 79          : optionsPosition.y - optionsSize
 80      }
 81  
 82      return 0
 83    }
 84  
 85    return ReactDOM.createPortal(
 86      <div className={type === ContextMenuEnum.CATEGORY || darkTheme ? 'dark' : ''}>
 87        <div
 88          ref={contextMenuRef}
 89          className="options-context-menu"
 90          style={{
 91            visibility: getOptionsYPosition() ? 'visible' : 'hidden',
 92            position: 'absolute',
 93            top: getOptionsYPosition() + 'px',
 94            left: optionsPosition.x + 'px',
 95          }}
 96          onClick={(event) => {
 97            event.stopPropagation()
 98          }}
 99        >
100          <MenuUtilitiesContext.Provider value={contextValues}>
101            {type === ContextMenuEnum.CATEGORY ? (
102              <CategoryMenu category={item as CategoryItem} />
103            ) : (
104              <NotesMenu note={item as NoteItem} setOptionsId={setOptionsId} />
105            )}
106          </MenuUtilitiesContext.Provider>
107        </div>
108      </div>,
109      document.getElementById('context-menu') as HTMLElement
110    )
111  }
112  
113  interface CategoryMenuProps {
114    category: CategoryItem
115  }
116  
117  const CategoryMenu: React.FC<CategoryMenuProps> = ({ category }) => {
118    return <ContextMenuOptions clickedItem={category} type={ContextMenuEnum.CATEGORY} />
119  }
120  
121  interface NotesMenuProps {
122    note: NoteItem
123    setOptionsId: (id: string) => void
124  }
125  
126  const NotesMenu: React.FC<NotesMenuProps> = ({ note, setOptionsId }) => {
127    // ===========================================================================
128    // Selectors
129    // ===========================================================================
130  
131    const { categories } = useSelector(getCategories)
132    const { activeCategoryId } = useSelector(getNotes)
133  
134    // ===========================================================================
135    // Dispatch
136    // ===========================================================================
137  
138    const dispatch = useDispatch()
139  
140    const _addCategoryToNote = (categoryId: string, noteId: string) =>
141      dispatch(addCategoryToNote({ categoryId, noteId }))
142    const _updateActiveNote = (noteId: string, multiSelect: boolean) =>
143      dispatch(updateActiveNote({ noteId, multiSelect }))
144    const _updateActiveCategoryId = (categoryId: string) =>
145      dispatch(updateActiveCategoryId(categoryId))
146  
147    return !isDraftNote(note) ? (
148      <>
149        {!note.scratchpad && (
150          <SelectCategory
151            onChange={(event) => {
152              _addCategoryToNote(event.target.value, note.id)
153  
154              if (event.target.value !== activeCategoryId) {
155                _updateActiveCategoryId(event.target.value)
156                _updateActiveNote(note.id, false)
157              }
158  
159              setOptionsId('')
160            }}
161            categories={categories}
162            activeCategoryId={activeCategoryId}
163            note={note}
164          />
165        )}
166        <ContextMenuOptions type={ContextMenuEnum.NOTE} clickedItem={note} />
167      </>
168    ) : null
169  }
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (15)

- [y] N Function_Component:CategoryMenu
- [y] N Function_Component:ContextMenu
- [y] N Function_Component:NotesMenu
- [y] N Context:MenuUtilitiesContext
- [y] N Prop:CategoryMenu::category
- [y] N Prop:ContextMenu::contextMenuRef
- [y] N Prop:ContextMenu::item
- [y] N Prop:NotesMenu::note
- [y] N Prop:ContextMenu::optionsPosition
- [y] N Prop:ContextMenu::setOptionsId
- [y] N Prop:NotesMenu::setOptionsId
- [y] N Prop:ContextMenu::type
- [y] N State_Variable:ContextMenu::elementDimensions
- [n] N EventHandler:NotesMenu::inline_onChange # cause: llm: onChange is a prop passed to child SelectCategory, not a native JSX event binding in NotesMenu
- [y] N EventHandler:ContextMenu::inline_onClick

### LLM-extracted edges (36)

- [y] E ACCEPTS_PROP Function_Component:CategoryMenu -> Prop:CategoryMenu::category
- [y] E ACCEPTS_PROP Function_Component:ContextMenu -> Prop:ContextMenu::contextMenuRef
- [y] E ACCEPTS_PROP Function_Component:ContextMenu -> Prop:ContextMenu::item
- [y] E ACCEPTS_PROP Function_Component:ContextMenu -> Prop:ContextMenu::optionsPosition
- [y] E ACCEPTS_PROP Function_Component:ContextMenu -> Prop:ContextMenu::setOptionsId
- [y] E ACCEPTS_PROP Function_Component:ContextMenu -> Prop:ContextMenu::type
- [y] E ACCEPTS_PROP Function_Component:NotesMenu -> Prop:NotesMenu::note
- [y] E ACCEPTS_PROP Function_Component:NotesMenu -> Prop:NotesMenu::setOptionsId
- [y] E DECLARES_STATE Function_Component:ContextMenu -> State_Variable:ContextMenu::elementDimensions
- [y] E DEFINED_IN Function_Component:CategoryMenu -> File
- [y] E DEFINED_IN Function_Component:ContextMenu -> File
- [y] E DEFINED_IN Function_Component:NotesMenu -> File
- [y] E HAS_HANDLER Function_Component:ContextMenu -> EventHandler:ContextMenu::inline_onClick
- [n] E HAS_HANDLER Function_Component:NotesMenu -> EventHandler:NotesMenu::inline_onChange # cause: llm: child-component callback prop, not a handler owned by NotesMenu
- [y] E PASSES_PROP Function_Component:CategoryMenu -> Function_Component:ContextMenuOptions@src/client/containers/ContextMenuOptions.tsx prop=clickedItem
- [y] E PASSES_PROP Function_Component:CategoryMenu -> Function_Component:ContextMenuOptions@src/client/containers/ContextMenuOptions.tsx prop=type
- [y] E PASSES_PROP Function_Component:ContextMenu -> Function_Component:CategoryMenu prop=category
- [y] E PASSES_PROP Function_Component:ContextMenu -> Function_Component:NotesMenu prop=note
- [y] E PASSES_PROP Function_Component:ContextMenu -> Function_Component:NotesMenu prop=setOptionsId
- [y] E PASSES_PROP Function_Component:NotesMenu -> Function_Component:ContextMenuOptions@src/client/containers/ContextMenuOptions.tsx prop=clickedItem
- [y] E PASSES_PROP Function_Component:NotesMenu -> Function_Component:ContextMenuOptions@src/client/containers/ContextMenuOptions.tsx prop=type
- [y] E PASSES_PROP Function_Component:NotesMenu -> Function_Component:SelectCategory@src/client/components/NoteList/SelectCategory.tsx prop=activeCategoryId
- [y] E PASSES_PROP Function_Component:NotesMenu -> Function_Component:SelectCategory@src/client/components/NoteList/SelectCategory.tsx prop=categories
- [y] E PASSES_PROP Function_Component:NotesMenu -> Function_Component:SelectCategory@src/client/components/NoteList/SelectCategory.tsx prop=note
- [y] E PASSES_PROP Function_Component:NotesMenu -> Function_Component:SelectCategory@src/client/components/NoteList/SelectCategory.tsx prop=onChange
- [y] E PROVIDES_CONTEXT Function_Component:ContextMenu -> Context:MenuUtilitiesContext
- [y] E USES_COMPONENT Function_Component:CategoryMenu -> Function_Component:ContextMenuOptions@src/client/containers/ContextMenuOptions.tsx
- [y] E USES_COMPONENT Function_Component:ContextMenu -> Function_Component:CategoryMenu
- [y] E USES_COMPONENT Function_Component:ContextMenu -> Function_Component:NotesMenu
- [y] E USES_COMPONENT Function_Component:NotesMenu -> Function_Component:ContextMenuOptions@src/client/containers/ContextMenuOptions.tsx
- [y] E USES_COMPONENT Function_Component:NotesMenu -> Function_Component:SelectCategory@src/client/components/NoteList/SelectCategory.tsx
- [y] E USES_LIBRARY_HOOK Function_Component:ContextMenu -> Library_Hook:useEffect@react
- [y] E USES_LIBRARY_HOOK Function_Component:ContextMenu -> Library_Hook:useSelector@react-redux
- [y] E USES_LIBRARY_HOOK Function_Component:ContextMenu -> Library_Hook:useState@react
- [y] E USES_LIBRARY_HOOK Function_Component:NotesMenu -> Library_Hook:useDispatch@react-redux
- [y] E USES_LIBRARY_HOOK Function_Component:NotesMenu -> Library_Hook:useSelector@react-redux

### Deterministic (sanity scope) (6)

- [y] N File
- [y] E BELONGS_TO File -> Project:takenote
- [y] E PROVIDED_BY Library_Hook:useDispatch@react-redux -> Library:react-redux
- [y] E PROVIDED_BY Library_Hook:useEffect@react -> Library:react
- [y] E PROVIDED_BY Library_Hook:useSelector@react-redux -> Library:react-redux
- [y] E PROVIDED_BY Library_Hook:useState@react -> Library:react

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->

<!-- wp6:missed-end -->
