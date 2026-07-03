/**
 * HireFlow AI — Frontend Entry Point
 *
 * This is the main JavaScript module loaded by index.html.
 * A framework (React, Vue, etc.) will be added in a later issue.
 * For now, this provides the minimal entry that Vite's build requires.
 */

export function greet(name) {
  return `Welcome to HireFlow, ${name}!`;
}

// Only manipulate the DOM when running in a browser context.
// In test environments (Node), 'document' is not defined unless jsdom is used.
if (typeof document !== "undefined") {
  const appEl = document.querySelector("#app");
  if (appEl) {
    appEl.innerHTML = `
      <h1>HireFlow AI</h1>
      <p>Frontend scaffold — ready for development.</p>
    `;
  }
}
