# yomiage

VOICEVOX COREでDiscordのテキストチャンネル投稿をボイスチャンネルへ読み上げるPython botです。
[`tanetakumi/voicebot`](https://github.com/tanetakumi/voicebot) のRust実装を参考に、
単体で動かしやすい構成へ移植しています。

## 機能

- `/join`: 実行者がいるボイスチャンネルへ参加
- Botへのメンション: メンションした人がいるボイスチャンネルへ参加
- `/leave`: ボイスチャンネルから退出
- `/skip`: 再生中の読み上げを停止
- `/s`: `/skip` の短縮版
- `/dict add|remove|list`: サーバー辞書の管理
- `/voice list|license`: VOICEVOXのキャラクター名、話者ID、クレジット表記を表示
- `/settings show|mention|read_name|default_speaker|user_speaker|clear_user_speaker`: 読み上げ設定
- 参加時のテキストチャンネルに投稿されたメッセージをVOICEVOX COREで読み上げ
- VC接続時にBot自身をSelf Deafにして、他ユーザーの音声を受信しない
- 接続中のVCから人が全員退出したら自動退出
- Rust版と同じ考え方のトークンバケット式レート制限
- SQLiteによるローカル辞書保存
- URL、時刻、コード片、括弧などの簡易読み替え
- Discordメンション、ロール、チャンネル、DiscordチャンネルURLの読み替え
- 投稿者名の読み上げ
- ユーザーごとのVOICEVOX話者ID設定
- 音声合成モードの切り替え（通常合成 / ストリーミング合成 / 自動）。`.env` で設定

## 対応OS

**実行環境はLinux (x86_64) を想定しています。** CIも `ubuntu-latest` 上でのみ実行しています。

開発・テスト用に、Windows (x86_64) でも公式の `voicevox_core` wheel を使って `uv sync` と
`pytest` などを実行できるようにしています。ただしWindows上でのBot実行は検証していません。

## 必要なもの

- Linux
- Python 3.12
- uv
- ffmpeg
- Discord Bot Token
- VOICEVOX CORE の実行ファイル一式

Discord Developer Portalでは、Botに次の権限とIntentを付けてください。

- `MESSAGE CONTENT INTENT`
- `View Channels`
- `Send Messages`
- `Read Message History`
- `Connect`
- `Speak`
- `Use Voice Activity`

VOICEVOX CORE はPyPIだけでは完結しません。このプロジェクトではPython wheelを依存に含めていますが、
実行時には別途VOICEVOX COREのONNX Runtime、OpenJTalk辞書、`.vvm` モデルが必要です。
`VOICEVOX_MODEL_PATH` に `.vvm` ファイルを指定した場合、そのファイルと同じディレクトリにある
`.vvm` もまとめてロードします。ディレクトリ自体を指定した場合は、その中の `.vvm` をロードします。

## セットアップ

1. 依存関係をインストールします。

```bash
uv sync
```

2. 環境変数ファイルを作ります。

```bash
cp .env.example .env
```

3. `.env` を編集します。最低限、次の値を設定してください。

```env
DISCORD_BOT_TOKEN=あなたのDiscord Botトークン
VOICEVOX_ONNXRUNTIME_PATH=./voicevox_core/onnxruntime/lib/libvoicevox_onnxruntime.so.1.17.3
OPEN_JTALK_DIC_DIR=./voicevox_core/dict/open_jtalk_dic_utf_8-1.11
VOICEVOX_MODEL_PATH=./voicevox_core/models/vvms
VOICEVOX_MODEL_EXCLUDE=
VOICEVOX_ACCELERATION_MODE=CPU
VOICEVOX_SYNTHESIS_MODE=normal
```

4. Botを起動します。

```bash
uv run yomiage
```

起動後、DiscordでBotをメンションするか `/join` を実行すると、実行者が参加しているVCへ接続します。

## VOICEVOX CORE の配置例

`.env.example` のデフォルト値は、リポジトリ直下に `voicevox_core/` を置く想定です。

```text
voicevox_core/
├── onnxruntime/lib/libvoicevox_onnxruntime.so.1.17.3
├── dict/open_jtalk_dic_utf_8-1.11/
└── models/vvms/0.vvm
```

配置場所を変える場合は、`.env` の `VOICEVOX_ONNXRUNTIME_PATH`、
`OPEN_JTALK_DIC_DIR`、`VOICEVOX_MODEL_PATH` を変更してください。

## VOICEVOX CORE 0.17.1 への更新

このプロジェクトは VOICEVOX CORE **0.17.1** のPython wheelを使います（`uv sync` で入ります）。
0.16系からの主な違いは次のとおりです。

- **ONNX Runtime**: 推奨バージョンが1.23.2になりました。1.17〜1.29に対応しており、従来の
  `libvoicevox_onnxruntime.so.1.17.3` も引き続き使えます。1.23.2に更新する場合は
  `VOICEVOX_ONNXRUNTIME_PATH=./voicevox_core/onnxruntime/lib/libvoicevox_onnxruntime.so.1.23.2`
  のように設定してください。
- **新形式VVM**: 新形式（`vvm_format_version=2`）のVVMを読み込めるようになりました。
  ストリーミング合成ができるのは、新形式VVMに含まれる `streaming_talk` タイプのスタイルだけです。
- **旧形式VVM**: 0.16系で使っていたVVMもそのまま読み込めます。ただしスタイルが `talk` タイプなので、
  通常合成でのみ使われます。
- **CPU/GPU設定**: `VOICEVOX_ACCELERATION_MODE` とモデルの遅延ロードの動作は変わりません。

公式ダウンローダーで新形式VVMを取得する例です（詳細は
[公式ドキュメント](https://github.com/VOICEVOX/voicevox_core/blob/0.17.1/docs/guide/user/downloader.md)）。

```bash
./download --only models --models-version 0.17.0
```

VVMの形式は、次のコマンドで確認できます（`2` なら新形式です）。

```bash
unzip -p ./voicevox_core/models/vvms/0.vvm manifest.json | jq .vvm_format_version
```

新しいVVMに入れ替えたら、起動ログの `Available VOICEVOX style IDs` と
`Streaming-capable VOICEVOX style IDs` を確認してください。また、`/voice list` で話者IDを確認し、
`VOICEVOX_SPEAKER_ID` やサーバー・ユーザーごとの話者ID設定がまだ存在するかを確かめてください。

## 音声合成モード

`.env` の `VOICEVOX_SYNTHESIS_MODE` で音声合成の方式を選びます。値の大文字・小文字は区別しません。
設定は全サーバー共通です。**変更はBotの再起動後に反映されます。**
Discordコマンドでは変更できず、SQLiteにも保存しません。

| モード | 動作 |
| :- | :- |
| `normal`（デフォルト） | 従来どおり、音声全体を合成してから再生します。ストリーミング機能は使いません。 |
| `streaming` | `streaming_synthesis()` で約0.3秒ずつ合成し、合成が終わるのを待たずに再生を始めます。 |
| `auto` | 対応しているスタイルではストリーミングを使い、それ以外は通常合成を使います。 |

```env
VOICEVOX_SYNTHESIS_MODE=auto
```

各モードの細かな動作は次のとおりです。

- **`streaming`**:
  - 起動時に `VOICEVOX_SPEAKER_ID` が `streaming_talk` スタイルかどうかを確認します。
    対応していない場合はエラーになり、起動しません。
  - ユーザーが非対応の話者IDを設定している場合は、警告ログを出したうえで通常合成で読み上げます。
  - 合成中にエラーが起きた場合は、そのメッセージを読み上げずにスキップします（再試行はしません）。
- **`auto`**:
  - ストリーミング合成が**再生開始前に**失敗した場合だけ、通常合成でもう一度読み上げます。
  - **再生開始後**に失敗した場合は、同じ文を二重に読み上げないよう、通常合成には切り替えません。
    それまでに合成できた部分だけを再生します。
  - 同じスタイルで3回続けて失敗すると、そのスタイルは再起動まで通常合成に固定されます。
    これにより、失敗による再試行が際限なく続くのを防ぎます。

どのモードでも、音声キャッシュ（`VOICEVOX_CACHE_SIZE`）にある文は合成を省略して即座に再生します。
ストリーミングで合成した音声も、最後まで合成できた場合に限りキャッシュします。
`/skip` や合成エラーで途中までしか合成しなかった音声はキャッシュしません。

### ストリーミングのバッファ設定

| 変数 | デフォルト | 説明 |
| :- | :- | :- |
| `VOICEVOX_STREAM_SEGMENT_SECONDS` | `0.3` | 1回に合成する長さ（秒）。VOICEVOX COREのデフォルトと同じ値です。0.0054より大きく10以下で指定します。 |
| `VOICEVOX_STREAM_BUFFER_SECONDS` | `0.5` | 再生を始める前に貯めておく音声の長さ（秒）。0以上10以下で指定します。 |

- バッファが貯まる前に合成が終わった短い文は、待たずにすぐ再生します。
- 再生中にバッファが空になった場合（アンダーラン）は無音を流します。その後、
  `VOICEVOX_STREAM_BUFFER_SECONDS` 分が貯まってから再生を再開します。
- バッファの上限は「2秒」と「バッファ秒数 + セグメント秒数×2」の大きいほうです。上限に達すると、
  再生が進むまで合成を一時停止します。
- 音切れが多いときは `VOICEVOX_STREAM_BUFFER_SECONDS` を増やしてください。CPUが遅く、
  合成が再生に追いつかない場合は `VOICEVOX_STREAM_SEGMENT_SECONDS` も少し大きくしてください。
- 読み上げ開始をもっと早くしたい場合は、`VOICEVOX_STREAM_BUFFER_SECONDS` を減らしてください。

### 性能ログ

`VOICEVOX_PERFORMANCE_LOG=true` にすると、読み上げ1件ごとに次のようなログを出力します。

```text
INFO yomiage.perf: speech_perf guild=123 mode=auto path=streaming cache_hit=false outcome=completed synthesis_start_ms=0.4 first_audio_ms=180.2 playback_start_ms=545.9 synthesis_total_ms=812.7 playback_end_ms=2650.3 underruns=0
```

時間はすべて、そのメッセージの読み上げ処理を開始した時点からのミリ秒です。

| 項目 | 内容 |
| :- | :- |
| `mode` | 設定されているモード |
| `path` | 実際に使った方式（`normal` / `streaming` / `streaming->normal`（フォールバック）/ `cache`） |
| `cache_hit` | キャッシュにあったかどうか |
| `outcome` | 結果（`completed` / `cancelled`（skip・退出）/ `failed`） |
| `synthesis_start_ms` | 合成スレッドで合成を始めた時刻 |
| `first_audio_ms` | 最初の音声データができた時刻（通常合成では音声全体ができた時刻） |
| `playback_start_ms` | Discordの再生スレッドが最初に音声を読み出した時刻 |
| `synthesis_total_ms` | 合成開始から合成完了までの時間。合成ロックの待ち時間を含みます。ストリーミングでは、バッファが上限に達して合成を一時停止していた時間も含みます |
| `playback_end_ms` | 再生が終わった時刻 |
| `underruns` | アンダーランが起きた回数（ストリーミング時のみ） |

実際に計測できなかった値（キャッシュヒット時の合成時間など）は `n/a` と表示します。推定値は出しません。
通常合成とストリーミング合成の速さを比べるには、同じ文を `normal` と `streaming` でそれぞれ読み上げて、
`playback_start_ms` を比べてください。このとき2回目以降はキャッシュにヒットするので、
`VOICEVOX_CACHE_SIZE=0` にするか、別の文で比べてください。

### トラブルシューティング

- **`VOICEVOX_SYNTHESIS_MODE=streaming requires ...` と表示されて起動しない**:
  デフォルト話者が新形式VVMの `streaming_talk` スタイルではありません。次のいずれかで対処してください。
  - 新形式VVMを導入する
  - 起動ログの `Streaming-capable VOICEVOX style IDs` にある話者IDを `VOICEVOX_SPEAKER_ID` に指定する
  - `auto` を使う
- **`VOICEVOX_SYNTHESIS_MODE must be one of ...` と表示される**: 値は `normal`、`streaming`、
  `auto` のいずれかにしてください。
- **`auto` にしてもストリーミングにならない**: 性能ログの `path` を確認してください。
  - `path=normal` の場合: そのスタイルが `streaming_talk` ではありません（旧形式VVMの可能性があります）。
  - `path=streaming->normal` の場合: ストリーミングに失敗しています。直前の警告ログを確認してください。
  - 3回続けて失敗したスタイルは、再起動まで通常合成に固定されます。
- **音が途切れる、または `underruns` が増える**: 合成が再生に追いついていません。
  - `VOICEVOX_STREAM_BUFFER_SECONDS` を増やしてください。
  - `VOICEVOX_ACCELERATION_MODE=GPU` の利用を検討してください。
  - VOICEVOX COREのPython API（非asyncio版）は、合成中にPythonのGILを保持します
    （[voicevox_core#1476](https://github.com/VOICEVOX/voicevox_core/issues/1476)）。
    そのため、複数サーバーで同時に読み上げると再生スレッドの動作が遅れることがあります。
- **`/skip` の後に次の読み上げが少し遅れる**: 停止の時点で合成中だったセグメント（約0.3秒分）は、
  合成が終わるまで待ちます。通常合成の場合は、合成中の音声全体を待ちます。

## 低遅延再生のしくみ

1. 合成スレッドが `streaming_synthesis()` から順にPCMセグメントを受け取ります。
   各セグメントの合成はVOICEVOXのロックを取得して行うので、他のサーバーと交互に合成されます。
2. 受け取ったセグメントは、その場でDiscord用の48kHz・16-bit・ステレオに変換します。
   補間に必要なデータを次のセグメントへ引き継ぐので、セグメントの境界でノイズは出ません。
3. 変換した音声は20ms単位のフレームに分けて `discord.AudioSource`（`StreamingPCMSource`）に貯めます。
   Discordの再生スレッドは、ここから音声を読み出して再生します。
4. 合成と再生は並行して進みます。全セグメントがそろうまで待つことはありません。
   ストリーミング再生ではffmpegを使いません。

`/skip`、`/leave`、自動退出、再接続、Bot終了のときは、次の処理を行います。

- 再生を止め、バッファを破棄します。
- 合成スレッドは、合成中のセグメントが終わった時点で停止します。
- 古いセッションの音声が、新しいセッションで再生されることはありません。

## Discord コマンド

- `/join`: 実行したテキストチャンネルを読み上げ対象にして、実行者のVCへ接続
- `@Bot`: 投稿した人のVCへ接続し、そのテキストチャンネルを読み上げ対象に設定
- `/leave`: VCから退出
- `/skip`: 現在の読み上げを停止
- `/s`: `/skip` の短縮版
- `s`, `S`, `!s`, `!S`, `！s`, `！S`: テキスト投稿で読み上げを停止
- `/dict add`: サーバー辞書へ単語を追加
- `/dict remove`: サーバー辞書から単語を削除
- `/dict list`: サーバー辞書を表示
- `/voice list`: VOICEVOXのキャラクター名、スタイル、話者IDを埋め込みで表示
- `/voice license`: VOICEVOXキャラクターのクレジット表記と利用規約URLを埋め込みで表示

`/voice` の一覧はページ移動ボタン付きで1ページずつ表示します。ボタンは1分後に消えます。

## 読み上げ設定

- `/settings show`: 現在の設定を表示
- `/settings mention mode:名前/チャンネル名`: メンションやDiscordチャンネルURLを名前で読む
- `/settings mention mode:リンク省略`: メンションやDiscordチャンネルURLを `りんくしょうりゃく` と読む
- `/settings read_name enabled:true`: 読み上げ前に投稿者名を読む
- `/settings read_name enabled:false`: 投稿者名を読まない
- `/settings serverchat enabled:true`: ServerChat形式の先頭 `[...]<...>` を読まない
- `/settings serverchat enabled:false`: ServerChat形式の先頭 `[...]<...>` をそのまま読む
- `/settings default_speaker speaker_id:<ID>`: サーバーのデフォルト話者IDを変更
- `/settings user_speaker speaker_id:<ID>`: 自分の話者IDを設定
- `/settings clear_user_speaker`: 自分の話者ID設定を解除

これらのスラッシュコマンドはDiscordの `サーバー管理` 権限なしで実行できます。

## 開発用コマンド

```bash
uv run ruff check .
uv run basedpyright src
uv run pytest
uv build
```

`uv build` の成果物は `dist/` に出力されます。`dist/`、`.venv/`、`.env`、SQLite DB、
VOICEVOX CORE本体はGit管理対象外です。

### テスト

`tests/` 配下に、Discord接続やVOICEVOX COREの実モデルなしで実行できる単体テストを用意しています。

- `test_rate_limit.py`: トークンバケットのレート制限ロジック
- `test_translator.py`: 辞書適用・正規表現・英単語/ローマ字変換・文字数省略などのテキスト変換
- `test_config.py`: 環境変数の検証ロジック
- `test_database.py`: SQLiteへの読み書きとキャッシュの整合性
- `test_session.py`: ボイスセッションの生成・再接続時の後始末・終了処理
- `test_bot_voice.py`: VC接続時のSelf Deaf設定、`/skip` による合成中の読み上げのキャンセル
- `test_audio_stream.py`: PCM変換（48kHz・ステレオ化）、チャンク境界、20msフレーム分割、プリバッファ、アンダーラン、バックプレッシャー
- `test_streaming_session.py`: `normal` / `streaming` / `auto` の各モード、フォールバック、二重読み上げの防止、`/skip`・`/leave`・再接続、複数サーバーでの同時再生
- `test_voicevox_streaming.py`: 途中までしか合成しなかった音声をキャッシュしないこと、キャッシュキー、非対応VVMの扱い、起動時のモード検証

```bash
uv run pytest
```

### CI

`.github/workflows/ci.yml` で、push・PR時に `uv sync` → `ruff check` → `basedpyright` →
`pytest` → `uv build` を `ubuntu-latest` 上で実行しています。

## 環境変数

- `DISCORD_BOT_TOKEN`: Discord Bot token
- `BOT_ID`: 辞書を分けたい場合のbot ID。デフォルトは `0`
- `YOMIAGE_DB`: SQLite DBのパス。デフォルトは `yomiage.sqlite3`
- `MAX_TOKENS`: サーバーごとの読み上げトークン上限。デフォルトは `400`
- `VOICEVOX_SPEAKER_ID`: VOICEVOX話者ID。デフォルトは `3`
- `VOICEVOX_SPEED`: 話速。デフォルトは `1.2`
- `VOICEVOX_ONNXRUNTIME_PATH`: `libvoicevox_onnxruntime.so...` のパス（ONNX Runtime 1.17〜1.29に対応。推奨は1.23.2）
- `OPEN_JTALK_DIC_DIR`: OpenJTalk辞書ディレクトリ
- `VOICEVOX_MODEL_PATH`: `.vvm` モデルファイル、または `.vvm` を含むディレクトリ
- `VOICEVOX_MODEL_EXCLUDE`: 読み込まない `.vvm`。例: `4.vvm`、複数なら `4.vvm,9.vvm`
- `VOICEVOX_ACCELERATION_MODE`: `CPU`, `AUTO`, `GPU` のいずれか。デフォルトは `CPU`
- `VOICEVOX_CACHE_SIZE`: 音声合成キャッシュ数。デフォルトは `100`
- `FFMPEG_PATH`: ffmpegコマンド。デフォルトは `ffmpeg`
- `VOICEVOX_SYNTHESIS_MODE`: `normal`, `streaming`, `auto` のいずれか。デフォルトは `normal`。[音声合成モード](#音声合成モード)を参照
- `VOICEVOX_STREAM_SEGMENT_SECONDS`: ストリーミングで1回に合成する長さ（秒）。デフォルトは `0.3`
- `VOICEVOX_STREAM_BUFFER_SECONDS`: ストリーミングで再生を始める前に貯める長さ（秒）。デフォルトは `0.5`
- `VOICEVOX_PERFORMANCE_LOG`: `true` で読み上げごとの性能ログを出力。デフォルトは `false`

## ライセンス

このプロジェクトはMIT Licenseで公開しています。詳細は [LICENSE](LICENSE) を参照してください。

このプロジェクトは [`tanetakumi/voicebot`](https://github.com/tanetakumi/voicebot) を参考にした
Python実装です。VOICEVOX CORE、VOICEVOXの音声モデル、その他依存ライブラリにはそれぞれ別の
ライセンスや利用条件があります。利用・配布時はそれらの条件も確認してください。

## Rust版との違い

元リポジトリはRustのDiscord bot、gRPC TTS server、Envoy、PostgreSQLで構成されています。
このPython版はまず動かしやすさを優先し、gRPC/Envoy/PostgreSQLを省いて単一プロセスにまとめています。
