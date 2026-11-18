"""Phrases that belong to every call, whatever the scenario.

A scenario file holds the medical questions. These are the words around them that make a call sound like a
conversation: a short reaction to each answer, a second try when an answer was not understood, the offer to
leave a message for the doctor, and the hand-over to a person. All of them are synthesised once and cached,
so they cost no waiting during a call.

The Uzbek texts were written by a non-native speaker and must be read by one before real use.
"""

CALLBACK_MINUTES = 30  # named aloud in `operator_ok`: change the phrase together with the number

SAY = {
    # after the greeting: how to reach a person
    "hint": {
        "uz": "Agar jonli xodim bilan gaplashmoqchi bo'lsangiz, istalgan payt «operator» deng.",
        "ru": "Если захотите поговорить с сотрудником, в любой момент скажите «оператор».",
    },
    # short reactions, used in turn after an answer that raises no concern
    "ack1": {"uz": "Tushunarli.", "ru": "Понятно."},
    "ack2": {"uz": "Yaxshi, rahmat.", "ru": "Хорошо, спасибо."},
    "ack3": {"uz": "Rahmat.", "ru": "Спасибо."},
    # after an answer that is a warning sign
    "ack_flag": {
        "uz": "Tushundim, buni shifokoringizga albatta yetkazaman.",
        "ru": "Поняла, обязательно передам это вашему врачу.",
    },
    "retry": {
        "uz": "Kechirasiz, yaxshi eshitmadim. Iltimos, «ha» yoki «yo'q» deb javob bering.",
        "ru": "Простите, я не расслышала. Пожалуйста, ответьте «да» или «нет».",
    },
    # phone line only: the second try is answered with keys
    "retry_keys": {
        "uz": "Kechirasiz, tushunmadim. «Ha» bo'lsa bir raqamini, «yo'q» bo'lsa ikki raqamini bosing. Xodim bilan gaplashish uchun nolni bosing.",
        "ru": "Простите, я не поняла. Если «да», нажмите один, если «нет», нажмите два. Чтобы поговорить с сотрудником, нажмите ноль.",
    },
    # phone line only, when the polyclinic's number is set: the call is put through
    "operator_dial": {
        "uz": "Tushundim. Hozir sizni poliklinika xodimiga ulayman, iltimos, kutib turing.",
        "ru": "Поняла. Сейчас соединю вас с сотрудником поликлиники, пожалуйста, подождите.",
    },
    "appeal_q": {
        "uz": "Shifokoringizga aytmoqchi bo'lgan yana biror gapingiz bormi? Xabar qoldirishni xohlaysizmi?",
        "ru": "Хотите ли вы что-то ещё передать вашему врачу? Записать обращение?",
    },
    "appeal_go": {
        "uz": "Yaxshi. Signaldan keyin gapiring. Tugatgach, tugmani bosing.",
        "ru": "Хорошо. Говорите после сигнала. Когда закончите, нажмите кнопку.",
    },
    # on a phone line there is no button: a pause ends the message
    "appeal_go_line": {
        "uz": "Yaxshi. Signaldan keyin gapiring, men tinglayman.",
        "ru": "Хорошо. Говорите после сигнала, я слушаю.",
    },
    "appeal_ok": {
        "uz": "Rahmat. Murojaatingiz yozib olindi va shifokoringizga yuborildi.",
        "ru": "Спасибо. Ваше обращение записано и передано вашему врачу.",
    },
    "appeal_ok_nurse": {
        "uz": "Rahmat. Murojaatingiz yozib olindi va patronaj hamshirasiga yuborildi.",
        "ru": "Спасибо. Ваше обращение записано и передано патронажной медсестре.",
    },
    "appeal_fail": {
        "uz": "Kechirasiz, xabaringizni yozib ololmadim. Poliklinikaga qo'ng'iroq qilishingiz mumkin.",
        "ru": "Простите, не получилось записать обращение. Вы можете позвонить в поликлинику.",
    },
    "operator_ok": {
        "uz": "Tushundim. Poliklinika xodimi sizga yarim soat ichida qo'ng'iroq qiladi. Ahvolingiz og'irlashsa, bir yuz uch raqamiga qo'ng'iroq qiling.",
        "ru": "Поняла. Сотрудник поликлиники перезвонит вам в течение получаса. Если станет хуже, звоните по номеру сто три.",
    },
}


def say(lang):
    """Every phrase in one language, for the call page."""
    return {key: text.get(lang) or text["uz"] for key, text in SAY.items()}
