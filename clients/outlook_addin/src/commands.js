/*
 * commands.js — обработчики безпейновых команд ленты.
 *
 * Сейчас единственная кнопка использует Action type="ShowTaskpane" (открывает
 * taskpane.html), поэтому JS-обработчик не вызывается. Файл оставлен как точка
 * расширения: чтобы добавить кнопку «отправить в ЛЕС одним кликом без панели»,
 * объяви в манифесте Action type="ExecuteFunction" с FunctionName="quickPush"
 * и зарегистрируй её здесь через Office.actions.associate.
 */

Office.onReady(() => {
  // Пример заготовки безпейновой команды (не активна, пока не объявлена в манифесте):
  //
  // function quickPush(event) {
  //   const item = Office.context.mailbox.item;
  //   // ... собрать payload как в taskpane.js, fetch POST ...
  //   // обязательно завершить: event.completed();
  //   event.completed();
  // }
  // if (Office.actions && Office.actions.associate) {
  //   Office.actions.associate("quickPush", quickPush);
  // }
});
