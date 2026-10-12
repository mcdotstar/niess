// With the theme's instant navigation, a <model-viewer> comes up with its src attribute
// set and its src property not, and loads nothing (zensical 0.0.68, model-viewer 4.0.0;
// a page built without navigation.instant loads them). Setting the property again on
// each page the theme shows -- the first one included -- is what loads them.
document$.subscribe(() => customElements.whenDefined('model-viewer').then(() => {
  for (const viewer of document.querySelectorAll('model-viewer')) {
    viewer.src = viewer.getAttribute('src');
  }
}));
