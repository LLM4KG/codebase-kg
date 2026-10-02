/**
 * Task P4 — Feature addition: clear the cart.
 *
 * These tests verify the BEHAVIOR through the public `useCart` hook with the
 * REAL CartProvider (no useContext mock), so they are independent of where
 * `clearCart` is implemented:
 *   - `useCart` returns a `clearCart` function.
 *   - `clearCart()` empties the product list.
 *   - `clearCart()` resets the totals (quantity, price, installments) to 0.
 *   - `clearCart()` on an empty cart does not throw and leaves it empty.
 *
 * Written BEFORE the reference patch (adversarial mode per implementation plan).
 *
 * Valid alternative solutions that should also pass:
 *   - implement clearCart in useCartProducts and expose it through useCart,
 *     or implement it directly in useCart via useCartContext;
 *   - reset totals via updateCartTotal([]) or setTotal(<initial values>).
 * Would fail: clearing products without resetting the totals.
 * Not tested: the "Clear cart" button in Cart (same choice as P2's test,
 * which covers the reducer only).
 */
import { act, renderHook } from '@testing-library/react-hooks';
import { ReactNode } from 'react';
import { CartProvider, useCart } from 'contexts/cart-context';

import { mockCartProducts } from 'utils/test/mocks';

const wrapper = ({ children }: { children: ReactNode }) => (
  <CartProvider>{children}</CartProvider>
);

const setup = () => renderHook(() => useCart(), { wrapper });

describe('P4 - useCart exposes clearCart, which empties the cart and resets totals', () => {
  test('useCart returns a clearCart function', () => {
    const { result } = setup();
    expect(typeof (result.current as any).clearCart).toBe('function');
  });

  test('clearCart removes every product', () => {
    const { result } = setup();

    act(() => {
      result.current.addProduct({ ...mockCartProducts[0], quantity: 1 });
    });
    act(() => {
      result.current.addProduct({ ...mockCartProducts[1], quantity: 2 });
    });
    expect(result.current.products).toHaveLength(2);

    act(() => {
      (result.current as any).clearCart();
    });
    expect(result.current.products).toEqual([]);
  });

  test('clearCart resets the cart totals', () => {
    const { result } = setup();

    act(() => {
      result.current.addProduct({ ...mockCartProducts[0], quantity: 1 });
    });
    act(() => {
      result.current.addProduct({ ...mockCartProducts[1], quantity: 2 });
    });
    expect(result.current.total.productQuantity).toBe(3);
    expect(result.current.total.totalPrice).toBeGreaterThan(0);

    act(() => {
      (result.current as any).clearCart();
    });
    expect(result.current.total.productQuantity).toBe(0);
    expect(result.current.total.totalPrice).toBe(0);
    expect(result.current.total.installments).toBe(0);
  });

  test('clearCart on an empty cart does not throw and keeps it empty', () => {
    const { result } = setup();

    expect(() =>
      act(() => {
        (result.current as any).clearCart();
      })
    ).not.toThrow();
    expect(result.current.products).toEqual([]);
    expect(result.current.total.productQuantity).toBe(0);
  });
});
