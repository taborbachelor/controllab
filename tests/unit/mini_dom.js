// A minimal DOM for running the components in Node (tests only; no dependency).
// It models what components.js uses: elements and text nodes, attributes,
// textContent, children, input values, events and focus. Every mutation counts
// in DOM.writes, so a test can prove that rendering the same data twice
// changes nothing. `children` is a live collection WITHOUT array methods, as
// in a browser, so code that calls .some()/.forEach() on it fails here too.
const DOM = { writes: 0 };

class Collection {
  constructor(get) { this._get = get; }
  get length() { return this._get().length; }
  item(i) { return this._get()[i] || null; }
  [Symbol.iterator]() { return this._get()[Symbol.iterator](); }
}

class Text {
  constructor(data) { this.nodeType = 3; this.data = String(data); this.parentNode = null; }
  get textContent() { return this.data; }
  toHTML() { return this.data.replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
}

class Element {
  constructor(tag, ns) {
    this.nodeType = 1; this.tagName = tag; this.namespaceURI = ns || null;
    this.attributes = new Map(); this.childNodes = []; this.parentNode = null;
    this.listeners = {}; this._value = "";
    const self = this;
    this.children = new Proxy(new Collection(() => self.childNodes.filter((n) => n.nodeType === 1)), {
      get(target, prop) {
        if (typeof prop === "string" && /^\d+$/.test(prop)) return target.item(+prop);
        return Reflect.get(target, prop, target);
      },
    });
  }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); DOM.writes++; }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  hasAttribute(name) { return this.attributes.has(name); }
  removeAttribute(name) { if (this.attributes.delete(name)) DOM.writes++; }
  appendChild(node) { node.parentNode = this; this.childNodes.push(node); DOM.writes++; return node; }
  removeChild(node) { this.childNodes = this.childNodes.filter((n) => n !== node); node.parentNode = null; DOM.writes++; return node; }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(""); }
  set textContent(value) {
    for (const n of this.childNodes) n.parentNode = null;
    this.childNodes = value === "" ? [] : [new Text(value)];
    DOM.writes++;
  }
  get value() { return this._value; }
  set value(v) { this._value = String(v); DOM.writes++; }
  get offsetWidth() { return 0; }
  focus() { document.activeElement = this; }
  contains(node) { for (let n = node; n; n = n.parentNode) if (n === this) return true; return false; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  dispatch(type, props = {}) {
    const event = { type, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...props };
    for (let n = this; n; n = n.parentNode) for (const fn of (n.listeners && n.listeners[type]) || []) fn(event);
    return event;
  }
  click() { return this.dispatch("click"); }
  toHTML() {
    const attrs = [...this.attributes].map(([k, v]) => (v === "" ? ` ${k}` : ` ${k}="${v.replace(/"/g, "&quot;")}"`)).join("");
    return `<${this.tagName}${attrs}>${this.childNodes.map((n) => n.toHTML()).join("")}</${this.tagName}>`;
  }
}

globalThis.document = {
  activeElement: null,
  createElement: (tag) => new Element(tag),
  createElementNS: (ns, tag) => new Element(tag, ns),
  createTextNode: (data) => new Text(data),
};
globalThis.DOM = DOM;
