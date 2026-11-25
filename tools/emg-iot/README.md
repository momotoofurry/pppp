# EMG edge monitor: MQTT → TimescaleDB → Grafana

肌電介面「邊緣到儀表板」的資料管線。用真實的自我測試錄音（2026-11-23，兩次配戴）模擬邊緣節點的即時輸出，經 MQTT 傳到後端，驗證後寫進時序資料庫，在 Grafana 監控訊號品質、準確率和配戴之間的漂移。

和工廠的機台監控是同一種架構：

| 這裡 | 工廠 |
|---|---|
| 每次配戴（session） | 每批、每台機台 |
| 邊緣節點：STM32 + 橋接程式 | PLC、機台控制器 |
| 60 Hz 干擾、通道漂移 | 感測器雜訊、機台漂移 |
| 拒收格式錯誤的訊息、偵測跳號 | 資料驗證、掉包偵測 |

## 架構

```
edge/edge_export.py   錄音 → 每 100 ms 一筆：4 通道 RMS、60 Hz 干擾量、模型預測、提示標籤
        │  （離線算一次；論文程式庫唯讀掛載，模型是 report 35.97 的取對數 LDA）
        ▼
app/publish.py        邊緣節點重播：照錄音時間（可加速）送到 MQTT
        │  topic emg/<subject>/<session>/window，QoS 1；status 用 retained + last will
        ▼
mosquitto             MQTT broker
        ▼
app/ingest.py         訂閱 → schema.py 驗證 → 每 0.5 s 批次 COPY 寫入
        │  錯誤訊息進 emg_reject（附原因）；序號跳號進 ingest_gap
        ▼
TimescaleDB           emg_window（hypertable，原始資料保留 30 天）
                      emg_10s（continuous aggregate，10 秒摘要）
                      rest_hum_alert（放鬆時 60 Hz > 5 µV）、class_drift（和第一次配戴比的漂移）
        ▼
Grafana               EMG edge monitor（自動 provision，資料源、儀表板、告警規則都在 repo 裡）
        │  告警 webhook
        ▼
app/alerts.py         告警紀錄服務：寫進 alert_log，並轉發到 MQTT emg/alerts（QoS 1）
```

## 告警

`grafana/provisioning/alerting/emg.yml`，每 10 秒評估一次：

| 規則 | 條件 | 嚴重度 | 意義 |
|---|---|---|---|
| Mains hum during rest | 最近 1 分鐘，放鬆視窗裡 60 Hz > 5 µV 的超過 4 個 | warning | 這時候校正「放鬆」，模型會把市電干擾學成放鬆（report 35.97）；先把手臂移開電源線再校正 |
| Pipeline rejects or gaps | 最近 1 分鐘有拒收的訊息或序號跳號 | critical | 邊緣節點送錯格式，或資料在傳輸中遺失 |

每次觸發和解除都會寫進 `alert_log`，同時發到 MQTT 的 `emg/alerts`，其他程式（例如邊緣節點）可以訂閱並做出反應。儀表板最下面有告警紀錄表。

## 使用

在 WSL：

```bash
cd tools/emg-iot
docker compose up -d                                          # broker、資料庫、ingest、Grafana
docker compose run --rm publisher --session T00_d1_G --speed 20
docker compose run --rm publisher --session T00_d2_G --speed 20
```

儀表板：<http://localhost:3000/d/emg-edge>（匿名可看；管理者帳號 admin，密碼見 `GRAFANA_PASSWORD`，預設 `admin-local`）。所有連接埠只綁 127.0.0.1。

重新產生邊緣資料（需要 `rf-emg` 映像和自我測試的原始錄音；錄音不在公開 repo，見 `docs/資料.md`）：

```bash
docker run --rm --user 1000:1000 -e HOME=/tmp -v "$PWD/../..":/model:ro \
  -v /mnt/d/selftest_data:/sd:ro -v "$PWD":/iot -w /iot rf-emg \
  python edge/edge_export.py --dir /sd/T00 --days T00_d1_G T00_d2_G --out /iot/data
```

測試資料驗證：`--bad 3` 會多送 3 筆格式錯誤的訊息，應該出現在 `emg_reject`。

## 驗證結果（2026-11-25，20 倍速）

- 兩次配戴共 17,416 個視窗全部寫入，序號完整，0 個跳號。
- 3 筆錯誤訊息全部被擋下，原因分別是 JSON 解析失敗、seq、rms。
- 測試視窗的準確率兩天都是 86.2 %，和離線分析（report 35.97，取對數）相同。
- 放鬆時 60 Hz > 5 µV 的視窗：第 1 天 95 個（平均 14.2 µV），第 2 天 47 個（8.4 µV）。
- `class_drift` 和離線分析的配戴間差異逐項相同。
- 告警：重播第 1 天並送 2 筆錯誤訊息，兩條規則都在 10 秒內觸發（放鬆時超標 60 個視窗；2 筆拒收），約 1 分鐘後自動解除；觸發和解除共 4 筆都寫進 `alert_log`，也都在 MQTT `emg/alerts` 收到。

注意：資料庫已經存在時 `init.sql` 不會重跑。從舊版升級要手動建 `alert_log`（SQL 在 `db/init.sql`），或 `docker compose down -v` 重建（會清掉資料）。

## 還沒做

- 直接接板子即時串流：橋接程式送 UDP，需要加一個 UDP→MQTT 的轉接。
- 帳號、TLS：目前只在本機使用。
