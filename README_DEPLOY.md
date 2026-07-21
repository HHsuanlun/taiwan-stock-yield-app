# 部署到 Render

這個 App 不需要額外 Python 套件，已包含 Render 的部署設定。

1. 將此資料夾建立為 GitHub repository 並推送到 GitHub。
2. 登入 [Render](https://render.com/)，選擇 **New > Blueprint**。
3. 連結剛才的 GitHub repository；Render 會讀取根目錄的 `render.yaml`。
4. 確認服務名稱後按 **Apply**，等待部署完成。
5. Render 會提供 `https://<服務名稱>.onrender.com` 網址；直接分享此網址即可。

App 使用 FinMind 的公開 API 查詢股票資料。免費未登入 API 有請求頻率限制；目前程式對相同代號會快取 10 分鐘，避免重複查詢。
