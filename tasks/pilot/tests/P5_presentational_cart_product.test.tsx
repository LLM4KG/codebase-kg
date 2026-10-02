/**
 * Task P5 — Refactoring: make CartProduct presentational.
 *
 * These tests verify the BEHAVIOR of the refactored interface:
 *   1. CartProduct renders WITHOUT a CartProvider (it no longer calls useCart)
 *      and calls onRemove / onIncrease / onDecrease with the product.
 *   2. CartProducts, inside a real CartProvider, supplies the callbacks so the
 *      cart behaves as before: +, - and remove change the real cart state.
 *
 * Written BEFORE the reference patch (adversarial mode per implementation plan).
 *
 * Unpatched code fails part 1: CartProduct calls useCart, which throws
 * "useCartContext must be used within a CartProvider". Part 2 is a
 * behaviour-preservation guard and passes on unpatched code by design.
 *
 * Valid alternative solutions that should also pass:
 *   - bind the callbacks inline or through named handlers, in either component;
 *   - keep CartProduct's own handlers, as long as they call the props.
 * Would fail:
 *   - renaming the props (the statement names them);
 *   - keeping useCart inside CartProduct as a fallback (part 1 still throws).
 * The - button is disabled at quantity 1, so part 1 uses quantity 2.
 */
import { fireEvent, screen } from '@testing-library/react';
import { useEffect } from 'react';
import { renderWithThemeProvider } from 'utils/test/test-utils';
import { CartProvider, useCart } from 'contexts/cart-context';
import { mockCartProducts } from 'utils/test/mocks';

import CartProduct from 'components/Cart/CartProducts/CartProduct';
import CartProducts from 'components/Cart/CartProducts';

const product = { ...mockCartProducts[0], quantity: 2 };

describe('P5 - CartProduct is presentational', () => {
  const renderStandalone = () => {
    const onRemove = jest.fn();
    const onIncrease = jest.fn();
    const onDecrease = jest.fn();
    const Presentational = CartProduct as any;
    renderWithThemeProvider(
      <Presentational
        product={product}
        onRemove={onRemove}
        onIncrease={onIncrease}
        onDecrease={onDecrease}
      />
    );
    return { onRemove, onIncrease, onDecrease };
  };

  test('clicking remove calls onRemove with the product', () => {
    const { onRemove, onIncrease, onDecrease } = renderStandalone();
    fireEvent.click(screen.getByTitle('remove product from cart'));
    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledWith(product);
    expect(onIncrease).not.toHaveBeenCalled();
    expect(onDecrease).not.toHaveBeenCalled();
  });

  test('clicking + calls onIncrease with the product', () => {
    const { onRemove, onIncrease, onDecrease } = renderStandalone();
    fireEvent.click(screen.getByText('+'));
    expect(onIncrease).toHaveBeenCalledTimes(1);
    expect(onIncrease).toHaveBeenCalledWith(product);
    expect(onRemove).not.toHaveBeenCalled();
    expect(onDecrease).not.toHaveBeenCalled();
  });

  test('clicking - calls onDecrease with the product', () => {
    const { onRemove, onIncrease, onDecrease } = renderStandalone();
    fireEvent.click(screen.getByText('-'));
    expect(onDecrease).toHaveBeenCalledTimes(1);
    expect(onDecrease).toHaveBeenCalledWith(product);
    expect(onRemove).not.toHaveBeenCalled();
    expect(onIncrease).not.toHaveBeenCalled();
  });
});

describe('P5 - CartProducts wires the callbacks to the cart', () => {
  // Puts one product in the real cart, then renders CartProducts from cart state.
  const CartHarness = () => {
    const { products, addProduct } = useCart();
    useEffect(() => {
      addProduct({ ...mockCartProducts[0], quantity: 1 });
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return <CartProducts products={products} />;
  };

  const renderInCart = () =>
    renderWithThemeProvider(
      <CartProvider>
        <CartHarness />
      </CartProvider>
    );

  test('+ then - change the product quantity in the cart', () => {
    renderInCart();
    expect(screen.getByText(/Quantity: 1/)).toBeTruthy();

    fireEvent.click(screen.getByText('+'));
    expect(screen.getByText(/Quantity: 2/)).toBeTruthy();

    fireEvent.click(screen.getByText('-'));
    expect(screen.getByText(/Quantity: 1/)).toBeTruthy();
  });

  test('remove takes the product out of the cart', () => {
    renderInCart();
    fireEvent.click(screen.getByTitle('remove product from cart'));
    expect(screen.getByText(/Add some products in the cart/i)).toBeTruthy();
  });
});
