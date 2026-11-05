// Compatibility endpoint for installed clients. The replacement has one design.
export function setTheme() {
  if (typeof document !== 'undefined') document.documentElement.removeAttribute('data-theme');
}
setTheme();
