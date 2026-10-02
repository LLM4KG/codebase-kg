/**
 * Task P6 — Bug fix: category names that differ only in case are accepted as new.
 *
 * These tests drive the real CategoryList against a real store and check the
 * BEHAVIOR through the store's category list:
 *   Adding:
 *     1. "work" is rejected when "Work" exists.
 *     2. "  WORK  " is rejected too (trimming still applies).
 *     3. "Personal" is accepted (the normal path; guards a reject-everything fix).
 *   Renaming:
 *     4. Renaming "Home" to "work" is rejected when "Work" exists.
 *     5. Renaming "Home" to "Personal" is accepted (normal path).
 *
 * Written BEFORE the reference patch (adversarial mode per implementation plan).
 *
 * Unpatched code fails 1, 2 and 4: the comparison is case-sensitive.
 *
 * Valid alternative solutions that should also pass:
 *   - toLowerCase / toUpperCase on both sides, or localeCompare with
 *     sensitivity: 'base', inline or in a shared helper;
 *   - a reducer-level check in the category slice (needs Redux knowledge;
 *     record which each candidate does).
 */
import React from 'react'
import { act, fireEvent, render } from '@testing-library/react'
import { Provider } from 'react-redux'
import { configureStore } from '@reduxjs/toolkit'
import { DragDropContext } from 'react-beautiful-dnd'

import { TestID } from '@resources/TestID'
import rootReducer from '@/slices'
import { addCategory, setCategoryEdit } from '@/slices/category'
import { TempStateProvider } from '@/contexts/TempStateContext'
import { CategoryList } from '@/containers/CategoryList'

const setup = () => {
  const store = configureStore({ reducer: rootReducer })
  store.dispatch(addCategory({ id: '1', name: 'Work', draggedOver: false }))
  store.dispatch(addCategory({ id: '2', name: 'Home', draggedOver: false }))

  const component = render(
    <Provider store={store}>
      <TempStateProvider>
        <DragDropContext onDragEnd={() => {}}>
          <CategoryList />
        </DragDropContext>
      </TempStateProvider>
    </Provider>
  )

  const names = () => store.getState().categoryState.categories.map((c) => c.name)

  const addViaForm = (name: string) => {
    fireEvent.click(component.getByTestId(TestID.ADD_CATEGORY_BUTTON))
    fireEvent.change(component.getByTestId(TestID.NEW_CATEGORY_INPUT), {
      target: { value: name },
    })
    fireEvent.submit(component.getByTestId(TestID.NEW_CATEGORY_FORM))
  }

  const renameViaForm = (categoryId: string, name: string) => {
    act(() => {
      store.dispatch(setCategoryEdit({ id: categoryId, tempName: name }))
    })
    const input = component.getByTestId(TestID.CATEGORY_EDIT)
    fireEvent.submit(input.closest('form') as HTMLFormElement)
  }

  return { store, component, names, addViaForm, renameViaForm }
}

describe('P6 - duplicate category names are rejected case-insensitively', () => {
  it('rejects adding "work" when "Work" exists', () => {
    const { names, addViaForm } = setup()
    addViaForm('work')
    expect(names()).toEqual(['Work', 'Home'])
  })

  it('rejects adding "  WORK  " when "Work" exists', () => {
    const { names, addViaForm } = setup()
    addViaForm('  WORK  ')
    expect(names()).toEqual(['Work', 'Home'])
  })

  it('still adds a genuinely new category', () => {
    const { names, addViaForm } = setup()
    addViaForm('Personal')
    expect(names()).toEqual(['Work', 'Home', 'Personal'])
  })

  it('rejects renaming "Home" to "work" when "Work" exists', () => {
    const { names, renameViaForm } = setup()
    renameViaForm('2', 'work')
    expect(names()).toEqual(['Work', 'Home'])
  })

  it('still renames a category to a genuinely new name', () => {
    const { names, renameViaForm } = setup()
    renameViaForm('2', 'Personal')
    expect(names()).toEqual(['Work', 'Personal'])
  })
})
