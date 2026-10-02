# WP6 annotation — todoist · `src/components/AddTask.js`

<!-- wp6 v1 project=todoist path=src/components/AddTask.js sha=f998b9af73a1d533e52a9a3f5545216904faf077 graph=graph_export/todoist/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator: annotator_1

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `f998b9a`:

````js
  1  import React, { useState } from 'react';
  2  import { FaRegListAlt, FaRegCalendarAlt } from 'react-icons/fa';
  3  import moment from 'moment';
  4  import PropTypes from 'prop-types';
  5  import { firebase } from '../firebase';
  6  import { useSelectedProjectValue } from '../context';
  7  import { ProjectOverlay } from './ProjectOverlay';
  8  import { TaskDate } from './TaskDate';
  9  
 10  export const AddTask = ({
 11    showAddTaskMain = true,
 12    shouldShowMain = false,
 13    showQuickAddTask,
 14    setShowQuickAddTask,
 15  }) => {
 16    const [task, setTask] = useState('');
 17    const [taskDate, setTaskDate] = useState('');
 18    const [project, setProject] = useState('');
 19    const [showMain, setShowMain] = useState(shouldShowMain);
 20    const [showProjectOverlay, setShowProjectOverlay] = useState(false);
 21    const [showTaskDate, setShowTaskDate] = useState(false);
 22  
 23    const { selectedProject } = useSelectedProjectValue();
 24  
 25    const addTask = () => {
 26      const projectId = project || selectedProject;
 27      let collatedDate = '';
 28  
 29      if (projectId === 'TODAY') {
 30        collatedDate = moment().format('DD/MM/YYYY');
 31      } else if (projectId === 'NEXT_7') {
 32        collatedDate = moment().add(7, 'days').format('DD/MM/YYYY');
 33      }
 34  
 35      return (
 36        task &&
 37        projectId &&
 38        firebase
 39          .firestore()
 40          .collection('tasks')
 41          .add({
 42            archived: false,
 43            projectId,
 44            task,
 45            date: collatedDate || taskDate,
 46            userId: 'jlIFXIwyAL3tzHMtzRbw',
 47          })
 48          .then(() => {
 49            setTask('');
 50            setProject('');
 51            setShowMain('');
 52            setShowProjectOverlay(false);
 53          })
 54      );
 55    };
 56  
 57    return (
 58      <div
 59        className={showQuickAddTask ? 'add-task add-task__overlay' : 'add-task'}
 60        data-testid="add-task-comp"
 61      >
 62        {showAddTaskMain && (
 63          <div
 64            className="add-task__shallow"
 65            data-testid="show-main-action"
 66            onClick={() => setShowMain(!showMain)}
 67            onKeyDown={(e) => {
 68              if (e.key === 'Enter') setShowMain(!showMain);
 69            }}
 70            tabIndex={0}
 71            aria-label="Add task"
 72            role="button"
 73          >
 74            <span className="add-task__plus">+</span>
 75            <span className="add-task__text">Add Task</span>
 76          </div>
 77        )}
 78  
 79        {(showMain || showQuickAddTask) && (
 80          <div className="add-task__main" data-testid="add-task-main">
 81            {showQuickAddTask && (
 82              <>
 83                <div data-testid="quick-add-task">
 84                  <h2 className="header">Quick Add Task</h2>
 85                  <span
 86                    className="add-task__cancel-x"
 87                    data-testid="add-task-quick-cancel"
 88                    aria-label="Cancel adding task"
 89                    onClick={() => {
 90                      setShowMain(false);
 91                      setShowProjectOverlay(false);
 92                      setShowQuickAddTask(false);
 93                    }}
 94                    onKeyDown={(e) => {
 95                      if (e.key === 'Enter') {
 96                        setShowMain(false);
 97                        setShowProjectOverlay(false);
 98                        setShowQuickAddTask(false);
 99                      }
100                    }}
101                    tabIndex={0}
102                    role="button"
103                  >
104                    X
105                  </span>
106                </div>
107              </>
108            )}
109            <ProjectOverlay
110              setProject={setProject}
111              showProjectOverlay={showProjectOverlay}
112              setShowProjectOverlay={setShowProjectOverlay}
113            />
114            <TaskDate
115              setTaskDate={setTaskDate}
116              showTaskDate={showTaskDate}
117              setShowTaskDate={setShowTaskDate}
118            />
119            <input
120              className="add-task__content"
121              aria-label="Enter your task"
122              data-testid="add-task-content"
123              type="text"
124              value={task}
125              onChange={(e) => setTask(e.target.value)}
126            />
127            <button
128              type="button"
129              className="add-task__submit"
130              data-testid="add-task"
131              onClick={() =>
132                showQuickAddTask
133                  ? addTask() && setShowQuickAddTask(false)
134                  : addTask()
135              }
136            >
137              Add Task
138            </button>
139            {!showQuickAddTask && (
140              <span
141                className="add-task__cancel"
142                data-testid="add-task-main-cancel"
143                onClick={() => {
144                  setShowMain(false);
145                  setShowProjectOverlay(false);
146                }}
147                onKeyDown={(e) => {
148                  if (e.key === 'Enter') {
149                    setShowMain(false);
150                    setShowProjectOverlay(false);
151                  }
152                }}
153                aria-label="Cancel adding a task"
154                tabIndex={0}
155                role="button"
156              >
157                Cancel
158              </span>
159            )}
160            <span
161              className="add-task__project"
162              data-testid="show-project-overlay"
163              onClick={() => setShowProjectOverlay(!showProjectOverlay)}
164              onKeyDown={(e) => {
165                if (e.key === 'Enter') setShowProjectOverlay(!showProjectOverlay);
166              }}
167              tabIndex={0}
168              role="button"
169            >
170              <FaRegListAlt />
171            </span>
172            <span
173              className="add-task__date"
174              data-testid="show-task-date-overlay"
175              onClick={() => setShowTaskDate(!showTaskDate)}
176              onKeyDown={(e) => {
177                if (e.key === 'Enter') setShowTaskDate(!showTaskDate);
178              }}
179              tabIndex={0}
180              role="button"
181            >
182              <FaRegCalendarAlt />
183            </span>
184          </div>
185        )}
186      </div>
187    );
188  };
189  
190  AddTask.propTypes = {
191    showAddTaskMain: PropTypes.bool,
192    shouldShowMain: PropTypes.bool,
193    showQuickAddTask: PropTypes.bool,
194    setShowQuickAddTask: PropTypes.func,
195  };
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (23)

- [y] N Function_Component:AddTask
- [y] N Prop:AddTask::setShowQuickAddTask
- [y] N Prop:AddTask::shouldShowMain
- [y] N Prop:AddTask::showAddTaskMain
- [y] N Prop:AddTask::showQuickAddTask
- [y] N State_Variable:AddTask::project
- [y] N State_Variable:AddTask::showMain
- [y] N State_Variable:AddTask::showProjectOverlay
- [y] N State_Variable:AddTask::showTaskDate
- [y] N State_Variable:AddTask::task
- [y] N State_Variable:AddTask::taskDate
- [y] N EventHandler:AddTask::inline_onChange
- [y] N EventHandler:AddTask::inline_onClick
- [y] N EventHandler:AddTask::inline_onClick_2
- [y] N EventHandler:AddTask::inline_onClick_3
- [y] N EventHandler:AddTask::inline_onClick_4
- [y] N EventHandler:AddTask::inline_onClick_5
- [y] N EventHandler:AddTask::inline_onClick_6
- [y] N EventHandler:AddTask::inline_onKeyDown
- [y] N EventHandler:AddTask::inline_onKeyDown_2
- [y] N EventHandler:AddTask::inline_onKeyDown_3
- [y] N EventHandler:AddTask::inline_onKeyDown_4
- [y] N EventHandler:AddTask::inline_onKeyDown_5

### LLM-extracted edges (32)

- [y] E ACCEPTS_PROP Function_Component:AddTask -> Prop:AddTask::setShowQuickAddTask
- [y] E ACCEPTS_PROP Function_Component:AddTask -> Prop:AddTask::shouldShowMain
- [y] E ACCEPTS_PROP Function_Component:AddTask -> Prop:AddTask::showAddTaskMain
- [y] E ACCEPTS_PROP Function_Component:AddTask -> Prop:AddTask::showQuickAddTask
- [y] E DECLARES_STATE Function_Component:AddTask -> State_Variable:AddTask::project
- [y] E DECLARES_STATE Function_Component:AddTask -> State_Variable:AddTask::showMain
- [y] E DECLARES_STATE Function_Component:AddTask -> State_Variable:AddTask::showProjectOverlay
- [y] E DECLARES_STATE Function_Component:AddTask -> State_Variable:AddTask::showTaskDate
- [y] E DECLARES_STATE Function_Component:AddTask -> State_Variable:AddTask::task
- [y] E DECLARES_STATE Function_Component:AddTask -> State_Variable:AddTask::taskDate
- [y] E DEFINED_IN Function_Component:AddTask -> File
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onChange
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onClick
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onClick_2
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onClick_3
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onClick_4
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onClick_5
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onClick_6
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onKeyDown
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onKeyDown_2
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onKeyDown_3
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onKeyDown_4
- [y] E HAS_HANDLER Function_Component:AddTask -> EventHandler:AddTask::inline_onKeyDown_5
- [y] E PASSES_PROP Function_Component:AddTask -> Function_Component:ProjectOverlay@src/components/ProjectOverlay.js prop=setProject
- [y] E PASSES_PROP Function_Component:AddTask -> Function_Component:ProjectOverlay@src/components/ProjectOverlay.js prop=setShowProjectOverlay
- [y] E PASSES_PROP Function_Component:AddTask -> Function_Component:ProjectOverlay@src/components/ProjectOverlay.js prop=showProjectOverlay
- [y] E PASSES_PROP Function_Component:AddTask -> Function_Component:TaskDate@src/components/TaskDate.js prop=setShowTaskDate
- [y] E PASSES_PROP Function_Component:AddTask -> Function_Component:TaskDate@src/components/TaskDate.js prop=setTaskDate
- [y] E PASSES_PROP Function_Component:AddTask -> Function_Component:TaskDate@src/components/TaskDate.js prop=showTaskDate
- [y] E USES_COMPONENT Function_Component:AddTask -> Function_Component:ProjectOverlay@src/components/ProjectOverlay.js
- [y] E USES_COMPONENT Function_Component:AddTask -> Function_Component:TaskDate@src/components/TaskDate.js
- [y] E USES_LIBRARY_HOOK Function_Component:AddTask -> Library_Hook:useState@react

### Deterministic (sanity scope) (3)

- [y] N File
- [y] E BELONGS_TO File -> Project:todoist
- [y] E PROVIDED_BY Library_Hook:useState@react -> Library:react

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->
N Custom_Hook:useSelectedProjectValue@src/context/selected-project-context.js # cause: llm: src/context/index.js is a barrel file that only re-exports. The hook is defined in src/context/selected-project-context.js.
E USES_CUSTOM_HOOK Function_Component:AddTask -> Custom_Hook:useSelectedProjectValue@src/context/selected-project-context.js # cause: llm: src/context/index.js is a barrel file that only re-exports. The hook is defined in src/context/selected-project-context.js.
<!-- wp6:missed-end -->

