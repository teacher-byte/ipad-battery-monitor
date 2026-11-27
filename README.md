# iPad 電量監控站

每 15 分鐘自動從 Jamf Pro 讀取全校 iPad 電量，找出可能「充電線沒插好或壞掉」的平板。不用每天登入 Jamf，打開網頁就知道今天要去檢查哪幾台。

- 石門國小的正式網站：https://cagoooo.github.io/ipad-battery-monitor/
- 開源授權：MIT（可以自由使用、修改、分享，請保留 `LICENSE` 裡的原作者標示）
- 不用架主機、不用付費：GitHub Actions 抓資料，GitHub Pages 放網頁，Google Apps Script 當鬧鐘

## 它會做什麼

1. **每 15 分鐘**登入 Jamf，讀全校平板的電量與回報時間。
2. **每小時**請所有平板立刻回報一次電量（選用，開機又連上 Wi-Fi 的平板幾分鐘內就會更新）。
3. 依下表標出有問題的平板，整理成「今天要去檢查的平板」清單和「充電車總覽」。
4. 有新問題時推播到 Google Chat 聊天室（選用）。

| 標記 | 條件（數字都可以在 `config.json` 改） |
|---|---|
| 電量危險 | 低於 20% |
| 電量偏低 | 20–49% |
| 半夜沒充飽 | 學生車平板在 0:00–7:30 回報時不到 80%，而且之後沒有回升到 80% |
| 連續低電量 | 最新一次回報和「至少 2 小時前」的那次回報都低於 50%，而且沒有回升 |
| 很久沒回報 | 超過 72 小時沒有回報電量（畫面上的電量是舊的） |

## 列印巡車單

網頁右上角按「🖨️ 列印巡車單」（或直接按 Ctrl+P），會印出 A4 的巡車單：第一頁是今天要檢查的平板清單，附「換線後會充、換一格會充、平板充電孔」勾選欄；後面是每一台充電車的格子圖。要檢查的格子是粗框加 □，很久沒回報的是虛線框，每格也用一個字標出問題（危、低、夜、續、久），黑白印表機也看得懂。

## 分享卡片與新版本通知

- **分享到 LINE、Facebook**：網頁已設定好分享卡片（`site/og.png`，1200×630）。部署時程式會自動把卡片網址換成你自己專案的網址。圖上有石門國小的字樣，別校可以換成自己的圖，檔名維持 `og.png`、尺寸 1200×630。
- **新版本通知**：網頁有 Service Worker，斷線時也能打開上次的畫面。改了網頁程式要發布新版時，下面 5 個地方的版本號要一起改（例：`1.3.0` → `1.3.1`）：`site/version.json`、`site/sw.js` 的 `VERSION`、`site/app.js` 的 `APP_VERSION`、`site/index.html` 的 `?v=` 和頁尾版本號。老師開著網頁時，最晚 5 分鐘內會跳出「有新版本」提示，按「立即更新」就會載入新版。電量資料不受影響，一直都是即時抓的。

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `config.json` | **學校名稱、分車規則、判斷門檻。別校只要改這個檔** |
| `scripts/fetch_jamf.py` | 從 Jamf 抓資料、判斷問題、推播（只用 Python 標準函式庫） |
| `.github/workflows/monitor.yml` | GitHub 自動流程：抓資料 → 發布網頁 |
| `site/` | 網頁（純 HTML／CSS／JS，讀 `data.json`） |
| `gas/Code.gs` | Apps Script 鬧鐘：每 15 分鐘叫 GitHub 跑一次（GitHub 內建排程常延遲好幾小時，只當備援） |

---

## 給其他學校：改成自己的版本

大約需要 30～60 分鐘。需要：一個 GitHub 帳號、Jamf Pro 管理權限、（選用）一個 Google 帳號。

### ⚠️ 開始前先確認：平板名稱不能有學生姓名

GitHub 免費帳號的網頁一定是**公開的**，知道網址的人都看得到（已設定不讓搜尋引擎收錄）。網頁會顯示 Jamf 裡的**裝置名稱**和**使用者名稱**。

- ✅ 可以：`SMES-STU3-12`、`STU3-12`、`英語車-05`
- ❌ 不行：`王小明的 iPad`、使用者欄位填學生姓名或學號

如果你們學校的平板是用學生姓名命名，請先在 Jamf 改成編號再使用。

### 步驟 1：複製這個專案

到 https://github.com/cagoooo/ipad-battery-monitor 按右上角綠色的 **Use this template → Create a new repository**，名稱例如 `ipad-battery-monitor`，選 **Public**。

> 用 Fork 也可以，但 Fork 出來的專案預設會關掉自動流程，要到 **Actions** 分頁按「I understand my workflows, go ahead and enable them」。

### 步驟 2：在 Jamf 建立唯讀的 API 帳號（建議）

不建議直接用管理員帳密。到 Jamf Pro **設定 → 系統 → API 角色與用戶端**：

1. **API 角色**：新增一個角色，權限勾「讀取行動裝置」（Read Mobile Devices）。如果要用「每小時請平板回報」，再勾「傳送行動裝置清查要求」之類的權限（名稱以你的 Jamf 畫面為準，可以搜尋 Inventory）。
2. **API 用戶端**：新增用戶端，套用上面的角色、啟用，按「產生用戶端密碼」，記下 **用戶端 ID** 和 **用戶端密碼**（密碼只會出現一次）。

> **設定裡找不到「API 角色與用戶端」？** 由教育部／教育局統一建置的學校 Jamf，學校拿到的管理帳號通常看不到這個設定，也不能新增帳號（石門實際檢查確認）。這時有兩條路：
> 1. 先用學校的管理帳號密碼（填 `JAMF_USER`／`JAMF_PASSWORD`），石門目前就是這樣用，帳密只存在 GitHub Secrets。
> 2. 請教育局的 Jamf 管理者幫學校建一個 API 用戶端，權限只給「讀取行動裝置」和「傳送清查要求」，拿到後填 `JAMF_CLIENT_ID`／`JAMF_CLIENT_SECRET`。
>
> 兩種都設定時，程式先用 API 用戶端；用戶端失敗會自動改用帳號密碼，執行紀錄會寫出這次用哪一種登入。用戶端方式程式已支援，但石門還沒實際用過。

### 步驟 3：把帳密放進 GitHub 保險箱

到你的專案 **Settings → Secrets and variables → Actions**：

**Secrets 分頁**（機密，放進去後沒有人看得到內容）：

| 名稱 | 填什麼 |
|---|---|
| `JAMF_URL` | 你們的 Jamf 網址，例如 `https://xxxx.jamfcloud.com`（結尾不要加 `/`） |
| `JAMF_CLIENT_ID` / `JAMF_CLIENT_SECRET` | 步驟 2 的用戶端 ID 和密碼（有設定就優先使用） |
| `JAMF_USER` / `JAMF_PASSWORD` | 沒有用戶端時才填帳號密碼 |
| `GCHAT_WEBHOOK` | 選填：Google Chat 聊天室的 Webhook 網址（步驟 7） |

**Variables 分頁**（一般設定，選用）：

| 名稱 | 填什麼 |
|---|---|
| `JAMF_SEND_UPDATE_INVENTORY` | 填 `1` 就會每隔一段時間請所有平板立刻回報電量 |
| `JAMF_UPDATE_INTERVAL_MIN` | 多久請一次，預設 `60`（分鐘） |

### 步驟 4：改 `config.json`

在 GitHub 網頁上點 `config.json` → 右上角鉛筆圖示編輯：

- `school`：學校簡稱、全名、處室，會顯示在網頁標題和頁尾。
- `carts`：分車規則。`prefix` 是 Jamf 使用者名稱或裝置名稱裡的代號，`label` 是網頁上顯示的車名。
  - 代號要在名稱開頭，或前後有 `-`、`_`，例如 `STU3-12`、`SMES-STU3-12` 都會分到 `STU3`。
  - 名稱最後一段數字會當成車上的格號（`STU3-12` 就是 12 號）。
  - `kind` 填 `student` 會列入待檢查清單和推播；填 `teacher` 只顯示、不推播。
  - 對不到任何代號的平板會歸到「其他」。
- `thresholds`、`night`：判斷門檻和半夜的時間範圍，不確定就先不要改。

改完按 **Commit changes**。

### 步驟 5：開啟網頁發布

到 **Settings → Pages**，**Source** 選 **GitHub Actions**。

### 步驟 6：第一次執行

到 **Actions** 分頁 → 左邊選「iPad 電量監控（每 15 分鐘）」→ **Run workflow**。大約 1 分鐘後變綠色勾勾，網頁就在：

```
https://你的GitHub帳號.github.io/你的專案名稱/
```

變紅色叉叉的話，點進去看是哪一步失敗。最常見的是 Jamf 網址、帳密打錯，或步驟 5 沒開。

### 步驟 7（選用）：Google Chat 推播

在 Google Chat 建一個聊天室 → 聊天室名稱旁的選單 → **應用程式與整合 → Webhook** → 新增，複製網址，存成步驟 3 的 `GCHAT_WEBHOOK`。之後學生機有新問題（電量危險、半夜沒充飽、連續低電量）就會推播。同一台平板只有出現新的問題標記才會再通知（例如從「電量危險」多了「半夜沒充飽」），問題解除後又出現也會再通知，不會因為平板每小時回報就重複推播。「半夜沒充飽」每晚各算一次：前一晚通知過、隔天半夜還是沒充飽，會再提醒一次。

### 步驟 8（建議）：用 Google 鬧鐘取代 GitHub 排程

GitHub 內建的定時執行常常晚好幾個小時才跑，所以石門改用 Google Apps Script 當鬧鐘：

1. **建 GitHub 金鑰**：GitHub 右上角頭像 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
   - Repository access：**Only select repositories**，只選這個專案
   - Permissions：**Actions** 設 **Read and write**，其他都不用
   - 複製產生的金鑰（`github_pat_` 開頭）
2. **建 Apps Script**：到 https://script.google.com 新增專案，把 `gas/Code.gs` 的內容貼進去，把第一行的 `REPO` 改成「你的帳號/你的專案名稱」。
3. **存金鑰**：左邊齒輪「專案設定」→ 最下面「指令碼屬性」→ 新增屬性，名稱 `GITHUB_TOKEN`，值貼上金鑰。
4. **啟動**：回到編輯器，上方函式選 `setup` → 執行 → 照畫面按「審查權限 → 允許」。

之後每 15 分鐘會自動觸發。如果金鑰過期，Google 會寄「啟動失敗 HTTP 401」的通知信，到 GitHub 換一把新金鑰、更新指令碼屬性就好。

---

## 隱私與安全

- 帳密只放在 GitHub Secrets 和 Apps Script 指令碼屬性，程式碼裡沒有任何密碼。
- 網頁只顯示裝置名稱、使用者名稱、機型、電量和回報時間，不顯示序號、網路位址、UDID。
- 電量紀錄只保留 14 天。

## 授權

MIT License，詳見 [`LICENSE`](LICENSE)。歡迎各校改成自己的版本，也歡迎回饋改進建議。

---

Made with ❤️ by [阿凱老師](https://cagoooo.github.io/Akai/)・桃園市龍潭區石門國民小學
