/**
 * iPad 電量監控站的「鬧鐘」
 * GitHub 內建的定時執行常延遲好幾小時，所以改由 Google 的定時觸發器
 * 每 15 分鐘請 GitHub 跑一次抓電量的流程（cagoooo/ipad-battery-monitor）。
 *
 * GitHub 金鑰存在「指令碼屬性」GITHUB_TOKEN，不寫在程式碼裡。
 * 這把金鑰只有「啟動這個專案自動流程」的權限。
 */
var REPO = 'cagoooo/ipad-battery-monitor';  // 別校請改成「你的 GitHub 帳號/專案名稱」
var WORKFLOW = 'monitor.yml';
var EVERY_MINUTES = 15;

/** 每 15 分鐘由觸發器呼叫：請 GitHub 跑一次監控流程 */
function tick() {
  var token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('尚未設定 GITHUB_TOKEN');
  var res = UrlFetchApp.fetch('https://api.github.com/repos/' + REPO + '/actions/workflows/' + WORKFLOW + '/dispatches', {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28'
    },
    payload: JSON.stringify({ ref: 'main' }),
    muteHttpExceptions: true
  });
  var code = res.getResponseCode();
  if (code !== 204) {
    // 丟出錯誤，讓 Apps Script 的「執行項目」與失敗通知信看得到
    throw new Error('啟動失敗 HTTP ' + code + '：' + res.getContentText().slice(0, 200));
  }
  console.log('已請 GitHub 更新電量');
}

/** 第一次設定：存金鑰、建立每 15 分鐘的觸發器，並立刻試跑一次 */
function setup() {
  if (typeof BOOT_TOKEN !== 'undefined' && BOOT_TOKEN) {
    PropertiesService.getScriptProperties().setProperty('GITHUB_TOKEN', BOOT_TOKEN);
  }
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'tick') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('tick').timeBased().everyMinutes(EVERY_MINUTES).create();
  tick();
  console.log('設定完成：每 ' + EVERY_MINUTES + ' 分鐘觸發一次');
}
