// A minimal DOM for running the components in Node (tests only; no dependency).
// It models what components.js uses: elements and text nodes, attributes,
// textContent, children, and focus. Every mutation counts in DOM.writes, so a
// test can prove that rendering the same data twice changes nothing.
const DOM = { writes: 0 };

class Text {
  constructor(data) { this.nodeType = 3; this.data = String(data); this.parentNode = null; }
  get textContent() { return this.data; }
  toHTML() { return this.data.replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
}

class Element {
  constructor(tag, ns) {
    this.nodeType = 1; this.tagName = tag; this.namespaceURI = ns || null;
    this.attributes = new Map(); this.childNodes = []; this.parentNode = null;
  }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); DOM.writes++; }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  hasAttribute(name) { return this.attributes.has(name); }
  removeAttribute(name) { if (this.attributes.delete(name)) DOM.writes++; }
  appendChild(node) { node.parentNode = this; this.childNodes.push(node); DOM.writes++; return node; }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(""); }
  set textContent(value) {
    for (const n of this.childNodes) n.parentNode = null;
    this.childNodes = value === "" ? [] : [new Text(value)];
    DOM.writes++;
  }
  get offsetWidth() { return 0; }
  focus() { document.activeElement = this; }
  contains(node) { for (let n = node; n; n = n.parentNode) if (n === this) return true; return false; }
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
