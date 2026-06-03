// ★ 새로 배포한 웹앱 URL을 붙여넣으세요 ★
const GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbxAChOC7oESXjN4YhQgVmUrIETsEXTxu73D2Qz-stRHDRpVougu4g48JJFrHteE4COjjA/exec";

chrome.action.onClicked.addListener((tab) => {
    if (!tab.url.includes("plaync.com")) {
        console.log("PlayNC 창고 페이지를 먼저 열어주세요!");
        return;
    }

    chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
            // 💡 [핵심 해결] 언더바가 1개든 2개든, 클래스 이름에 'profile'과 'name/server'가 들어가면 무조건 찾아냅니다!
            const nameEl = document.querySelector('[class*="profile_name"]') || document.querySelector('[class*="profile__name"]');
            const serverEl = document.querySelector('[class*="profile_server"]') || document.querySelector('[class*="profile__server"]');

            const exactName = nameEl ? nameEl.innerText.trim() : "알 수 없음";
            const exactServer = serverEl ? serverEl.innerText.trim() : "아툰";

            return {
                html: document.documentElement.outerHTML,
                accountName: exactName,
                serverName: exactServer
            };
        }
    }, async (results) => {
        if (results && results[0] && results[0].result) {
            const data = results[0].result;
            console.log(`추출 완료: ${data.accountName} (${data.serverName})`);

            try {
                const payload = {
                    html: data.html,
                    accountName: data.accountName,
                    serverName: data.serverName
                };

                const res = await fetch(GAS_WEBAPP_URL, {
                    method: "POST",
                    body: JSON.stringify(payload),
                    headers: { "Content-Type": "text/plain;charset=utf-8" }
                });

                const result = await res.json();
                console.log("GAS 서버 응답:", result);
            } catch (error) {
                console.error("전송 실패:", error);
            }
        }
    });
});