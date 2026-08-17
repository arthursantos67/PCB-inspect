import "@testing-library/jest-dom/vitest";

// jsdom implements no scrolling at all, so `Element.scrollTo` is simply absent and any
// component that keeps a list pinned to the bottom throws on mount. A no-op is the whole
// contract here: nothing under test asserts on scroll position.
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}
