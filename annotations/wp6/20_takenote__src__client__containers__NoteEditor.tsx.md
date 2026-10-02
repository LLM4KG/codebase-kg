# WP6 annotation — takenote · `src/client/containers/NoteEditor.tsx`

<!-- wp6 v1 project=takenote path=src/client/containers/NoteEditor.tsx sha=e0eddbb9a21ae4cf4c4c7c183f29cfd666e08331 graph=graph_export/takenote/full_dump.cypherl prompt_set=72ef9f041851 -->

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
  1  import dayjs from 'dayjs'
  2  import React from 'react'
  3  import { Controlled as CodeMirror } from 'react-codemirror2'
  4  import { useDispatch, useSelector } from 'react-redux'
  5  import { Editor } from 'codemirror'
  6  
  7  import { getActiveNote } from '@/utils/helpers'
  8  import { updateNote } from '@/slices/note'
  9  import { NoteItem } from '@/types'
 10  import { NoteMenuBar } from '@/containers/NoteMenuBar'
 11  import { EmptyEditor } from '@/components/Editor/EmptyEditor'
 12  import { PreviewEditor } from '@/components/Editor/PreviewEditor'
 13  import { getNotes, getSettings, getSync } from '@/selectors'
 14  import { setPendingSync } from '@/slices/sync'
 15  
 16  import 'codemirror/lib/codemirror.css'
 17  import 'codemirror/theme/base16-light.css'
 18  import 'codemirror/mode/gfm/gfm'
 19  import 'codemirror/addon/selection/active-line'
 20  import 'codemirror/addon/scroll/scrollpastend'
 21  
 22  export const NoteEditor: React.FC = () => {
 23    // ===========================================================================
 24    // Selectors
 25    // ===========================================================================
 26  
 27    const { pendingSync } = useSelector(getSync)
 28    const { activeNoteId, loading, notes } = useSelector(getNotes)
 29    const { codeMirrorOptions, previewMarkdown } = useSelector(getSettings)
 30  
 31    const activeNote = getActiveNote(notes, activeNoteId)
 32  
 33    // ===========================================================================
 34    // Dispatch
 35    // ===========================================================================
 36  
 37    const dispatch = useDispatch()
 38  
 39    const _updateNote = (note: NoteItem) => {
 40      !pendingSync && dispatch(setPendingSync())
 41      dispatch(updateNote(note))
 42    }
 43  
 44    const setEditorOverlay = (editor: Editor) => {
 45      const query = /\{\{[^}]*}}/g
 46      editor.addOverlay({
 47        token: function (stream: any) {
 48          query.lastIndex = stream.pos
 49          var match = query.exec(stream.string)
 50          if (match && match.index == stream.pos) {
 51            stream.pos += match[0].length || 1
 52  
 53            return 'notelink'
 54          } else if (match) {
 55            stream.pos = match.index
 56          } else {
 57            stream.skipToEnd()
 58          }
 59        },
 60      })
 61    }
 62  
 63    const renderEditor = () => {
 64      if (loading) {
 65        return <div className="empty-editor v-center">Loading...</div>
 66      } else if (!activeNote) {
 67        return <EmptyEditor />
 68      } else if (previewMarkdown) {
 69        return (
 70          <PreviewEditor
 71            directionText={codeMirrorOptions.direction}
 72            noteText={activeNote.text}
 73            notes={notes}
 74          />
 75        )
 76      }
 77  
 78      return (
 79        <CodeMirror
 80          data-testid="codemirror-editor"
 81          className="editor mousetrap"
 82          value={activeNote.text}
 83          options={codeMirrorOptions}
 84          editorDidMount={(editor) => {
 85            setTimeout(() => {
 86              editor.focus()
 87            }, 0)
 88            editor.setCursor(0)
 89            setEditorOverlay(editor)
 90          }}
 91          onBeforeChange={(editor, data, value) => {
 92            _updateNote({
 93              id: activeNote.id,
 94              text: value,
 95              created: activeNote.created,
 96              lastUpdated: dayjs().format(),
 97            })
 98          }}
 99          onChange={(editor, data, value) => {
100            if (!value) {
101              editor.focus()
102            }
103          }}
104          onPaste={(editor, event: any) => {
105            // Get around pasting issue
106            // https://github.com/scniro/react-codemirror2/issues/77
107            if (!event.clipboardData || !event.clipboardData.items || !event.clipboardData.items[0])
108              return
109            event.clipboardData.items[0].getAsString((pasted: any) => {
110              if (editor.getSelection() !== pasted) return
111              const { anchor, head } = editor.listSelections()[0]
112              editor.setCursor({
113                line: Math.max(anchor.line, head.line),
114                ch: Math.max(anchor.ch, head.ch),
115              })
116            })
117          }}
118        />
119      )
120    }
121  
122    return (
123      <main className="note-editor">
124        <NoteMenuBar />
125        {renderEditor()}
126      </main>
127    )
128  }
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (5)

- [y] N Function_Component:NoteEditor
- [?] N EventHandler:NoteEditor::inline_editorDidMount # cause: llm: editorDidMount is a lifecycle callback, not an event handler. It fires once when the CodeMirror instance is created and does setup work.
- [y] N EventHandler:NoteEditor::inline_onBeforeChange
- [y] N EventHandler:NoteEditor::inline_onChange
- [y] N EventHandler:NoteEditor::inline_onPaste

### LLM-extracted edges (13)

- [y] E DEFINED_IN Function_Component:NoteEditor -> File
- [?] E HAS_HANDLER Function_Component:NoteEditor -> EventHandler:NoteEditor::inline_editorDidMount # cause: llm: editorDidMount is a lifecycle callback, not an event handler. It fires once when the CodeMirror instance is created and does setup work.
- [y] E HAS_HANDLER Function_Component:NoteEditor -> EventHandler:NoteEditor::inline_onBeforeChange
- [y] E HAS_HANDLER Function_Component:NoteEditor -> EventHandler:NoteEditor::inline_onChange
- [y] E HAS_HANDLER Function_Component:NoteEditor -> EventHandler:NoteEditor::inline_onPaste
- [y] E PASSES_PROP Function_Component:NoteEditor -> Function_Component:PreviewEditor@src/client/components/Editor/PreviewEditor.tsx prop=directionText
- [y] E PASSES_PROP Function_Component:NoteEditor -> Function_Component:PreviewEditor@src/client/components/Editor/PreviewEditor.tsx prop=noteText
- [y] E PASSES_PROP Function_Component:NoteEditor -> Function_Component:PreviewEditor@src/client/components/Editor/PreviewEditor.tsx prop=notes
- [y] E USES_COMPONENT Function_Component:NoteEditor -> Function_Component:EmptyEditor@src/client/components/Editor/EmptyEditor.tsx
- [y] E USES_COMPONENT Function_Component:NoteEditor -> Function_Component:NoteMenuBar@src/client/containers/NoteMenuBar.tsx
- [y] E USES_COMPONENT Function_Component:NoteEditor -> Function_Component:PreviewEditor@src/client/components/Editor/PreviewEditor.tsx
- [y] E USES_LIBRARY_HOOK Function_Component:NoteEditor -> Library_Hook:useDispatch@react-redux
- [y] E USES_LIBRARY_HOOK Function_Component:NoteEditor -> Library_Hook:useSelector@react-redux

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
