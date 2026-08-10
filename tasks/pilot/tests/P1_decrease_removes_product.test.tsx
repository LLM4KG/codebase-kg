/**
 * Task P1 — Bug fix: decreaseProductQuantity allows quantity to reach zero.
 *
 * These tests verify the BEHAVIOR, not the implementation:
 *   - Decreasing a quantity-1 product removes it from the cart.
 *   - Decreasing a quantity-2 product reduces it to 1 (normal path).
 *   - Cart total is updated correctly after auto-removal.
 *   - Other products in the cart are unaffected by the removal.
 *   - No product should ever remain in the cart with quantity <= 0.
 *
 * Written BEFORE the reference patch (adversarial mode per implementation plan).
 *
 * Valid alternative solutions that should also pass:
 *   - Guard at the top of decreaseProductQuantity, delegating to removeProduct
 *   - Normal decrease followed by filtering out zero-quantity products
 *   - Any approach that ensures no zero-quantity products remain and total updates
 */
import { renderHook } from '@testing-library/react-hooks';
import { ICartProduct } from 'models';
import React, { ReactNode } from 'react';
import { CartProvider } from 'contexts/cart-context';
import useCartProducts from 'contexts/cart-context/useCartProducts';
import * as useCartTotalModule from 'contexts/cart-context/useCartTotal';

import { mockCartProducts } from 'utils/test/mocks';

const wrapper = ({ children }: { children: ReactNode }) => (
  <CartProvider>{children}</CartProvider>
);

describe('P1 - decreaseProductQuantity should remove product at quantity 1', () => {
  let products: ICartProduct[];
  const originalUseContext = React.useContext;

  const setupMockUseContext = (initialProducts: ICartProduct[] = []) => {
    products = [...initialProducts];
    const mockSetProducts = jest
      .fn()
      .mockImplementation((updatedProducts: ICartProduct[]) => {
        products = [...updatedProducts];
        return products;
      });
    const mockUseContext = jest.fn().mockImplementation(() => ({
      products: initialProducts,
      setProducts: mockSetProducts,
    }));
    React.useContext = mockUseContext;
  };

  const setupCartTotalMock = () => {
    const mockUpdateCartTotal = jest.fn();
    useCartTotalModule.default = jest.fn().mockImplementation(() => ({
      total: {},
      updateCartTotal: mockUpdateCartTotal,
    }));
    return mockUpdateCartTotal;
  };

  afterEach(() => {
    React.useContext = originalUseContext;
  });

  test('should remove product from cart when decreasing from quantity 1', () => {
    const product = { ...mockCartProducts[0], quantity: 1 };
    setupMockUseContext([product]);
    setupCartTotalMock();

    const { result } = renderHook(() => useCartProducts(), { wrapper });

    expect(products).toHaveLength(1);
    result.current.decreaseProductQuantity(product);
    expect(products).toHaveLength(0);
  });

  test('should decrease quantity normally when quantity is greater than 1', () => {
    const product = { ...mockCartProducts[0], quantity: 2 };
    setupMockUseContext([product]);
    setupCartTotalMock();

    const { result } = renderHook(() => useCartProducts(), { wrapper });

    expect(products[0].quantity).toBe(2);
    result.current.decreaseProductQuantity(product);
    expect(products).toHaveLength(1);
    expect(products[0].quantity).toBe(1);
  });

  test('should update cart total with empty array after auto-removal', () => {
    const product = { ...mockCartProducts[0], quantity: 1 };
    setupMockUseContext([product]);
    const mockUpdateCartTotal = setupCartTotalMock();

    const { result } = renderHook(() => useCartProducts(), { wrapper });

    result.current.decreaseProductQuantity(product);
    expect(mockUpdateCartTotal).toHaveBeenCalledWith([]);
  });

  test('should keep other products when one is auto-removed by decrease', () => {
    const productToRemove = { ...mockCartProducts[0], quantity: 1 };
    const productToKeep = { ...mockCartProducts[1], quantity: 3 };
    setupMockUseContext([productToRemove, productToKeep]);
    setupCartTotalMock();

    const { result } = renderHook(() => useCartProducts(), { wrapper });

    expect(products).toHaveLength(2);
    result.current.decreaseProductQuantity(productToRemove);
    expect(products).toHaveLength(1);
    expect(products[0].id).toBe(productToKeep.id);
  });

  test('should not leave any product with quantity zero or below', () => {
    const product = { ...mockCartProducts[0], quantity: 1 };
    setupMockUseContext([product]);
    setupCartTotalMock();

    const { result } = renderHook(() => useCartProducts(), { wrapper });

    result.current.decreaseProductQuantity(product);
    const hasInvalidQuantity = products.some(
      (p: ICartProduct) => p.quantity <= 0
    );
    expect(hasInvalidQuantity).toBe(false);
  });
});
