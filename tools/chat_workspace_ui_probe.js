// Read-only browser regression probe. Evaluate this expression in the current
// chat page with the supported browser tool. It does not mutate the page.
(() => {
  const rect = el => el.getBoundingClientRect();
  const footer = document.querySelector('.sov-project-navigation-footer');
  const nav = document.querySelector('.sov-project-navigation');
  const rows = [...document.querySelectorAll('.sov-project-chat-list button')];
  const failures = [];
  const tolerance = 2;
  if (!nav || !footer) return {schema: 'les.chat-ui-regression.v1', failures: ['navigation_missing']};
  const navVisible = getComputedStyle(nav).display !== 'none';
  if (document.documentElement.scrollWidth > innerWidth + tolerance) failures.push('horizontal_page_overflow');
  if (document.documentElement.scrollHeight > innerHeight + tolerance) failures.push('vertical_page_overflow');
  if (navVisible) {
    const box = rect(footer);
    if (box.top < -tolerance || box.bottom > innerHeight + tolerance) failures.push('footer_outside_viewport');
    for (let ancestor = footer.parentElement; ancestor; ancestor = ancestor.parentElement) {
      if (['hidden', 'clip', 'auto', 'scroll'].includes(getComputedStyle(ancestor).overflowY)) {
        const clip = rect(ancestor);
        if (box.top < clip.top - tolerance || box.bottom > clip.bottom + tolerance) {
          failures.push('footer_clipped_by_ancestor');
          break;
        }
      }
    }
    if (rows.some(el => !el.classList.contains('sov-project-nav-row'))) failures.push('chat_button_render_aborted');
    if (rows.some(el => rect(el).height > 46)) failures.push('multiline_chat_row');
  }
  return {
    schema: 'les.chat-ui-regression.v1', viewport: [innerWidth, innerHeight],
    chat_count: rows.length, navigation_visible: navVisible,
    footer_bottom: navVisible ? rect(footer).bottom : null, failures,
  };
})()
