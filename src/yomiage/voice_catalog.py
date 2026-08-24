from __future__ import annotations

from dataclasses import dataclass

VOICE_LIST_PAGE_FIELD_LIMIT = 25
VOICE_LICENSE_PAGE_FIELD_LIMIT = 20


@dataclass(frozen=True)
class VoiceCatalogEntry:
    vvm: str
    character: str
    styles: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class VoiceLicenseEntry:
    character: str
    credit: str
    terms_url: str
    note: str = ""


VOICE_CATALOG: tuple[VoiceCatalogEntry, ...] = (
    VoiceCatalogEntry(
        "0.vvm",
        "四国めたん",
        (("あまあま", 0), ("ノーマル", 2), ("セクシー", 4), ("ツンツン", 6)),
    ),
    VoiceCatalogEntry(
        "0.vvm",
        "ずんだもん",
        (("あまあま", 1), ("ノーマル", 3), ("セクシー", 5), ("ツンツン", 7)),
    ),
    VoiceCatalogEntry("0.vvm", "春日部つむぎ", (("ノーマル", 8),)),
    VoiceCatalogEntry("0.vvm", "雨晴はう", (("ノーマル", 10),)),
    VoiceCatalogEntry("1.vvm", "冥鳴ひまり", (("ノーマル", 14),)),
    VoiceCatalogEntry(
        "2.vvm",
        "九州そら",
        (("あまあま", 15), ("ノーマル", 16), ("セクシー", 17), ("ツンツン", 18)),
    ),
    VoiceCatalogEntry("3.vvm", "波音リツ", (("ノーマル", 9), ("クイーン", 65))),
    VoiceCatalogEntry(
        "3.vvm",
        "中国うさぎ",
        (("ノーマル", 61), ("おどろき", 62), ("こわがり", 63), ("へろへろ", 64)),
    ),
    VoiceCatalogEntry("4.vvm", "玄野武宏", (("ノーマル", 11),)),
    VoiceCatalogEntry("4.vvm", "剣崎雌雄", (("ノーマル", 21),)),
    VoiceCatalogEntry("5.vvm", "四国めたん", (("ささやき", 36), ("ヒソヒソ", 37))),
    VoiceCatalogEntry("5.vvm", "ずんだもん", (("ささやき", 22), ("ヒソヒソ", 38))),
    VoiceCatalogEntry("5.vvm", "九州そら", (("ささやき", 19),)),
    VoiceCatalogEntry("6.vvm", "No.7", (("ノーマル", 29), ("アナウンス", 30), ("読み聞かせ", 31))),
    VoiceCatalogEntry("7.vvm", "後鬼", (("人間ver.", 27), ("ぬいぐるみver.", 28))),
    VoiceCatalogEntry(
        "8.vvm",
        "WhiteCUL",
        (("ノーマル", 23), ("たのしい", 24), ("かなしい", 25), ("びえーん", 26)),
    ),
    VoiceCatalogEntry(
        "9.vvm",
        "白上虎太郎",
        (("ふつう", 12), ("わーい", 32), ("びくびく", 33), ("おこ", 34), ("びえーん", 35)),
    ),
    VoiceCatalogEntry("10.vvm", "玄野武宏", (("喜び", 39), ("ツンギレ", 40), ("悲しみ", 41))),
    VoiceCatalogEntry("10.vvm", "ちび式じい", (("ノーマル", 42),)),
    VoiceCatalogEntry("11.vvm", "櫻歌ミコ", (("ノーマル", 43), ("第二形態", 44), ("ロリ", 45))),
    VoiceCatalogEntry(
        "11.vvm",
        "ナースロボ＿タイプＴ",
        (("ノーマル", 47), ("楽々", 48), ("恐怖", 49), ("内緒話", 50)),
    ),
    VoiceCatalogEntry("12.vvm", "†聖騎士 紅桜†", (("ノーマル", 51),)),
    VoiceCatalogEntry("12.vvm", "雀松朱司", (("ノーマル", 52),)),
    VoiceCatalogEntry("12.vvm", "麒ヶ島宗麟", (("ノーマル", 53),)),
    VoiceCatalogEntry("13.vvm", "春歌ナナ", (("ノーマル", 54),)),
    VoiceCatalogEntry("13.vvm", "猫使アル", (("ノーマル", 55), ("おちつき", 56), ("うきうき", 57))),
    VoiceCatalogEntry("13.vvm", "猫使ビィ", (("ノーマル", 58), ("おちつき", 59), ("人見知り", 60))),
    VoiceCatalogEntry("14.vvm", "栗田まろん", (("ノーマル", 67),)),
    VoiceCatalogEntry("14.vvm", "あいえるたん", (("ノーマル", 68),)),
    VoiceCatalogEntry(
        "14.vvm",
        "満別花丸",
        (("ノーマル", 69), ("元気", 70), ("ささやき", 71), ("ぶりっ子", 72), ("ボーイ", 73)),
    ),
    VoiceCatalogEntry("14.vvm", "琴詠ニア", (("ノーマル", 74),)),
    VoiceCatalogEntry("15.vvm", "ずんだもん", (("ヘロヘロ", 75), ("なみだめ", 76))),
    VoiceCatalogEntry(
        "15.vvm",
        "青山龍星",
        (
            ("ノーマル", 13),
            ("熱血", 81),
            ("不機嫌", 82),
            ("喜び", 83),
            ("しっとり", 84),
            ("かなしみ", 85),
            ("囁き", 86),
        ),
    ),
    VoiceCatalogEntry(
        "15.vvm",
        "もち子さん",
        (
            ("ノーマル", 20),
            ("セクシー／あん子", 66),
            ("泣き", 77),
            ("怒り", 78),
            ("喜び", 79),
            ("のんびり", 80),
        ),
    ),
    VoiceCatalogEntry("15.vvm", "小夜/SAYO", (("ノーマル", 46),)),
    VoiceCatalogEntry("16.vvm", "後鬼", (("人間（怒り）ver.", 87), ("鬼ver.", 88))),
    VoiceCatalogEntry("17.vvm", "Voidoll", (("ノーマル", 89),)),
    VoiceCatalogEntry(
        "18.vvm",
        "ぞん子",
        (("ノーマル", 90), ("低血圧", 91), ("覚醒", 92), ("実況風", 93)),
    ),
    VoiceCatalogEntry(
        "18.vvm",
        "中部つるぎ",
        (("ノーマル", 94), ("怒り", 95), ("ヒソヒソ", 96), ("おどおど", 97), ("絶望と敗北", 98)),
    ),
    VoiceCatalogEntry("19.vvm", "離途", (("ノーマル", 99), ("シリアス", 101))),
    VoiceCatalogEntry("19.vvm", "黒沢冴白", (("ノーマル", 100),)),
    VoiceCatalogEntry(
        "20.vvm",
        "ユーレイちゃん",
        (
            ("ノーマル", 102),
            ("甘々", 103),
            ("哀しみ", 104),
            ("ささやき", 105),
            ("ツクモちゃん", 106),
        ),
    ),
    VoiceCatalogEntry("21.vvm", "猫使アル", (("つよつよ", 110), ("へろへろ", 111))),
    VoiceCatalogEntry("21.vvm", "猫使ビィ", (("つよつよ", 112),)),
    VoiceCatalogEntry("21.vvm", "東北ずん子", (("ノーマル", 107),)),
    VoiceCatalogEntry("21.vvm", "東北きりたん", (("ノーマル", 108),)),
    VoiceCatalogEntry("21.vvm", "東北イタコ", (("ノーマル", 109),)),
    VoiceCatalogEntry(
        "22.vvm",
        "あんこもん",
        (("ノーマル", 113), ("つよつよ", 114), ("よわよわ", 115), ("けだるげ", 116)),
    ),
    VoiceCatalogEntry("23.vvm", "あんこもん", (("ささやき", 117),)),
    VoiceCatalogEntry(
        "24.vvm",
        "夜語トバリ",
        (("ノーマル", 118), ("明るい", 119), ("哀しみ", 120), ("呆れ", 121)),
    ),
    VoiceCatalogEntry(
        "24.vvm",
        "暁記ミタマ",
        (("ノーマル", 122), ("怒り", 123), ("哀しみ", 124), ("ささやき", 125)),
    ),
    VoiceCatalogEntry("24.vvm", "里石ユカ", (("つぼみ", 126),)),
)

VOICE_LICENSES: tuple[VoiceLicenseEntry, ...] = (
    VoiceLicenseEntry(
        "四国めたん", "VOICEVOX:四国めたん", "https://zunko.jp/con_ongen_kiyaku.html",
    ),
    VoiceLicenseEntry(
        "ずんだもん", "VOICEVOX:ずんだもん", "https://zunko.jp/con_ongen_kiyaku.html",
    ),
    VoiceLicenseEntry(
        "春日部つむぎ", "VOICEVOX:春日部つむぎ", "https://tsumugi-official.studio.site/rule",
    ),
    VoiceLicenseEntry("雨晴はう", "VOICEVOX:雨晴はう", "https://amehau.com/rules/amehare-hau-rule"),
    VoiceLicenseEntry(
        "冥鳴ひまり", "VOICEVOX:冥鳴ひまり", "https://meimeihimari.wixsite.com/himari/terms-of-use",
    ),
    VoiceLicenseEntry("九州そら", "VOICEVOX:九州そら", "https://zunko.jp/con_ongen_kiyaku.html"),
    VoiceLicenseEntry("波音リツ", "VOICEVOX:波音リツ", "http://canon-voice.com/kiyaku.html"),
    VoiceLicenseEntry(
        "中国うさぎ", "VOICEVOX:中国うさぎ", "https://zunko.jp/con_ongen_kiyaku.html",
    ),
    VoiceLicenseEntry(
        "玄野武宏", "VOICEVOX:玄野武宏", "https://www.virvoxproject.com/voicevoxの利用規約",
    ),
    VoiceLicenseEntry(
        "剣崎雌雄", "VOICEVOX:剣崎雌雄", "https://frontier.creatia.cc/fanclubs/413/posts/4507",
    ),
    VoiceLicenseEntry(
        "No.7", "VOICEVOX:No.7", "https://voiceseven.com/#j0200", "商用利用は事前確認が必要です。",
    ),
    VoiceLicenseEntry(
        "後鬼",
        "VOICEVOX:後鬼",
        "https://ついなちゃん.com/voicevox_terms/",
        "企業が携わる利用は事前確認が必要です。",
    ),
    VoiceLicenseEntry("WhiteCUL", "VOICEVOX:WhiteCUL", "https://www.whitecul.com/guideline"),
    VoiceLicenseEntry(
        "白上虎太郎", "VOICEVOX:白上虎太郎", "https://www.virvoxproject.com/voicevoxの利用規約",
    ),
    VoiceLicenseEntry(
        "ちび式じい",
        "VOICEVOX:ちび式じい",
        "https://docs.google.com/presentation/d/1AcD8zXkfzKFf2ertHwWRwJuQXjNnijMxhz7AJzEkaI4",
    ),
    VoiceLicenseEntry("櫻歌ミコ", "VOICEVOX:櫻歌ミコ", "https://voicevox35miko.studio.site/rule"),
    VoiceLicenseEntry(
        "ナースロボ＿タイプＴ", "VOICEVOX:ナースロボ＿タイプＴ", "https://www.krnr.top/rules",
    ),
    VoiceLicenseEntry(
        "†聖騎士 紅桜†", "VOICEVOX:†聖騎士 紅桜†", "https://commons.nicovideo.jp/material/nc296132",
    ),
    VoiceLicenseEntry(
        "雀松朱司", "VOICEVOX:雀松朱司", "https://www.virvoxproject.com/voicevoxの利用規約",
    ),
    VoiceLicenseEntry(
        "麒ヶ島宗麟", "VOICEVOX:麒ヶ島宗麟", "https://www.virvoxproject.com/voicevoxの利用規約",
    ),
    VoiceLicenseEntry(
        "春歌ナナ", "VOICEVOX:春歌ナナ", "https://nanahira.jp/haruka_nana/guideline.html",
    ),
    VoiceLicenseEntry(
        "猫使アル", "VOICEVOX:猫使アル", "https://nekotukarb.wixsite.com/nekonohako/利用規約",
    ),
    VoiceLicenseEntry(
        "猫使ビィ", "VOICEVOX:猫使ビィ", "https://nekotukarb.wixsite.com/nekonohako/利用規約",
    ),
    VoiceLicenseEntry("栗田まろん", "VOICEVOX:栗田まろん", "https://aivoice.jp/character/maron/"),
    VoiceLicenseEntry(
        "あいえるたん",
        "VOICEVOX:あいえるたん",
        "https://www.infiniteloop.co.jp/special/iltan/terms/",
    ),
    VoiceLicenseEntry(
        "満別花丸", "VOICEVOX:満別花丸", "https://100hanamaru.wixsite.com/manbetsu-hanamaru/rule",
    ),
    VoiceLicenseEntry(
        "琴詠ニア", "VOICEVOX:琴詠ニア", "https://commons.nicovideo.jp/works/nc315435",
    ),
    VoiceLicenseEntry(
        "青山龍星",
        "VOICEVOX:青山龍星",
        "https://www.virvoxproject.com/voicevoxの利用規約",
        "企業が携わる利用は事前確認が必要です。",
    ),
    VoiceLicenseEntry(
        "もち子さん",
        "VOICEVOX:もち子(cv 明日葉よもぎ)",
        "https://vtubermochio.wixsite.com/mochizora/利用規約",
        "企業が携わる利用は事前確認が必要です。",
    ),
    VoiceLicenseEntry(
        "小夜/SAYO", "VOICEVOX:小夜/SAYO", "https://316soramegu.wixsite.com/sayo-official/guideline",
    ),
    VoiceLicenseEntry(
        "Voidoll",
        "VOICEVOX:Voidoll(CV:丹下桜)",
        "https://blog.nicovideo.jp/niconews/224589.html",
        "法人利用は個別問い合わせが必要です。",
    ),
    VoiceLicenseEntry(
        "ぞん子",
        "VOICEVOX:ぞん子",
        "https://zonko.zone-energy.jp/guideline",
        "商用利用は個別問い合わせが必要です。",
    ),
    VoiceLicenseEntry(
        "中部つるぎ", "VOICEVOX:中部つるぎ", "https://zunko.jp/con_ongen_kiyaku.html",
    ),
    VoiceLicenseEntry("離途", "VOICEVOX:離途", "https://litmus9.com/#/voicebank#rules"),
    VoiceLicenseEntry(
        "黒沢冴白", "VOICEVOX:黒沢冴白", "https://www.virvoxproject.com/voicevoxの利用規約",
    ),
    VoiceLicenseEntry(
        "ユーレイちゃん",
        "VOICEVOX:ユーレイちゃん(CV:神崎零)",
        "https://u-stella.co.jp/voicevox-ure-chan-tucumo-terms-of-use/",
        "商用利用は事前確認が必要です。",
    ),
    VoiceLicenseEntry(
        "東北ずん子", "VOICEVOX:東北ずん子", "https://zunko.jp/con_ongen_kiyaku.html",
    ),
    VoiceLicenseEntry(
        "東北きりたん", "VOICEVOX:東北きりたん", "https://zunko.jp/con_ongen_kiyaku.html",
    ),
    VoiceLicenseEntry(
        "東北イタコ", "VOICEVOX:東北イタコ", "https://zunko.jp/con_ongen_kiyaku.html",
    ),
    VoiceLicenseEntry(
        "あんこもん", "VOICEVOX:あんこもん", "https://zunko.jp/con_ongen_kiyaku.html",
    ),
    VoiceLicenseEntry(
        "夜語トバリ", "VOICEVOX:夜語トバリ", "https://yogataritobari.studio.site/#rules",
    ),
    VoiceLicenseEntry(
        "暁記ミタマ", "VOICEVOX:暁記ミタマ", "https://yogataritobari.studio.site/#rules",
    ),
    VoiceLicenseEntry(
        "里石ユカ",
        "VOICEVOX:里石ユカ（つぼみ）",
        "https://satoishiyuka.wixsite.com/satoishi/kiyaku",
    ),
)


def format_voice_styles(entry: VoiceCatalogEntry) -> str:
    return " / ".join(f"{style} `{style_id}`" for style, style_id in entry.styles)


def format_voice_license(entry: VoiceLicenseEntry) -> str:
    lines = [f"表記: `{entry.credit}`", f"規約: {entry.terms_url}"]
    if entry.note:
        lines.append(entry.note)
    return "\n".join(lines)


def voice_catalog_pages() -> tuple[tuple[VoiceCatalogEntry, ...], ...]:
    return tuple(
        VOICE_CATALOG[index : index + VOICE_LIST_PAGE_FIELD_LIMIT]
        for index in range(0, len(VOICE_CATALOG), VOICE_LIST_PAGE_FIELD_LIMIT)
    )


def voice_license_pages() -> tuple[tuple[VoiceLicenseEntry, ...], ...]:
    return tuple(
        VOICE_LICENSES[index : index + VOICE_LICENSE_PAGE_FIELD_LIMIT]
        for index in range(0, len(VOICE_LICENSES), VOICE_LICENSE_PAGE_FIELD_LIMIT)
    )
