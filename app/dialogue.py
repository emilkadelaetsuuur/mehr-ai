"""Phrases that belong to every call, whatever the scenario.

A scenario file holds the medical questions. These are the words around them that make a call sound like a
conversation: a short reaction to each answer, a second try when an answer was not understood, the offer to
leave a message for the doctor, and the hand-over to a person. All of them are synthesised once and cached,
so they cost no waiting during a call.

The Uzbek texts were written by a non-native speaker and must be read by one before real use.
"""

CALLBACK_MINUTES = 30  # named aloud in `operator_ok`: change the phrase together with the number

SAY = {
    "private_later": {
        "ru": "Хорошо. Поликлиника уточнит удобное время. Всего доброго.",
        "uz": "Mayli. Poliklinika sizga qulay vaqtni aniqlaydi. Salomat bo‘ling.",
    },
    # The call opens by asking whether the right person picked up (app/talk.py words that question, with her name).
    "who_retry": {
        "uz": "Kechirasiz, yaxshi eshitmadim. Bu sizmisiz? Iltimos, «ha» yoki «yo'q» deng.",
        "ru": "Простите, я не расслышала. Это вы? Пожалуйста, скажите «да» или «нет».",
    },
    # someone else picked up: nothing about health is said, the call ends and is made again later
    "who_no": {
        "uz": "Tushunarli, bezovta qilganim uchun uzr. Iltimos, unga poliklinikadan qo'ng'iroq bo'lganini aytib qo'ying. "
        "Keyinroq qayta qo'ng'iroq qilamiz. Sog' bo'ling!",
        "ru": "Понятно, извините за беспокойство. Пожалуйста, передайте ей, что звонили из поликлиники. Мы перезвоним позже. Всего доброго!",
    },
    # a call about dispensary follow-up asks a second key after the name; a wrong one ends the call
    "who_year": {"uz": "Rahmat. Xavfsizlik uchun tug'ilgan yilingizni ayting.", "ru": "Спасибо. Для безопасности назовите, пожалуйста, год вашего рождения."},
    "who_year_no": {
        "uz": "Kechirasiz, ma'lumot mos kelmadi, shuning uchun suhbatni to'xtataman. Poliklinikaga o'zingiz murojaat qilishingiz mumkin. Sog' bo'ling!",
        "ru": "Простите, данные не совпали, поэтому я завершаю разговор. Вы можете сами обратиться в поликлинику. Всего доброго!",
    },
    # the offer to a first-time mother: a few words from the leaflet without being asked
    "tips_q_baby": {
        "uz": "Bu sizning birinchi farzandingiz. Chaqaloq parvarishi bo'yicha eng muhim maslahatlarni qisqacha aytib beraymi?",
        "ru": "Это ваш первый ребёнок. Рассказать коротко самое важное об уходе за малышом?",
    },
    "tips_q_preg": {
        "uz": "Bu sizning birinchi homiladorligingiz. Nimalarga e'tibor berish kerakligini qisqacha aytib beraymi?",
        "ru": "Это ваша первая беременность. Рассказать коротко, на что важно обращать внимание?",
    },
    "who_fail": {
        "uz": "Kechirasiz, sizni eshita olmadim. Keyinroq qayta qo'ng'iroq qilaman. Sog' bo'ling!",
        "ru": "Простите, я вас не слышу. Перезвоню позже. Всего доброго!",
    },
    # Her own questions, after the scenario's. An answer comes from the leaflet (app/advice.json) and is worded
    # for this call; these are the fixed phrases around it.
    # The invitation names only what concerns the person called: nobody under dispensary follow-up is asked
    # about babies, no parent of a healthy child about treatment (app/talk.py picks the one that fits).
    "ask_q": {
        "uz": "Endi sizni tinglayman. Sog'lig'ingiz yoki davolanishingiz haqida savolingiz bormi? "
        "Yoki shifokoringizga aytmoqchi bo'lgan gapingiz bo'lsa, ayting. Bo'lmasa, «yo'q» deng.",
        "ru": "Теперь я слушаю вас. Есть ли у вас вопрос о самочувствии или лечении? Или скажите, что передать вашему врачу. Если вопросов нет, скажите «нет».",
    },
    "ask_q_homilador": {
        "uz": "Endi sizni tinglayman. Homiladorlik, ovqatlanish yoki o'zingizni qanday his qilayotganingiz haqida savolingiz bormi? "
        "Yoki shifokoringizga aytmoqchi bo'lgan gapingiz bo'lsa, ayting. Bo'lmasa, «yo'q» deng.",
        "ru": "Теперь я слушаю вас. Есть ли у вас вопрос о беременности, питании или самочувствии? "
        "Или скажите, что передать вашему врачу. Если вопросов нет, скажите «нет».",
    },
    "ask_q_ona": {
        "uz": "Endi sizni tinglayman. O'z sog'lig'ingiz yoki chaqaloq parvarishi haqida savolingiz bormi? "
        "Yoki shifokoringizga aytmoqchi bo'lgan gapingiz bo'lsa, ayting. Bo'lmasa, «yo'q» deng.",
        "ru": "Теперь я слушаю вас. Есть ли у вас вопрос о вашем самочувствии или уходе за малышом? "
        "Или скажите, что передать вашему врачу. Если вопросов нет, скажите «нет».",
    },
    "ask_q_bola": {
        "uz": "Endi sizni tinglayman. Emlash yoki bolangizning sog'lig'i haqida savolingiz bormi? "
        "Yoki shifokoringizga aytmoqchi bo'lgan gapingiz bo'lsa, ayting. Bo'lmasa, «yo'q» deng.",
        "ru": "Теперь я слушаю вас. Есть ли у вас вопрос о прививках или здоровье ребёнка? "
        "Или скажите, что передать вашему врачу. Если вопросов нет, скажите «нет».",
    },
    "ask_q_dispanser": {
        "uz": "Endi sizni tinglayman. Davolanish yoki dorilar haqida savolingiz bormi? "
        "Yoki shifokoringizga aytmoqchi bo'lgan gapingiz bo'lsa, ayting. Bo'lmasa, «yo'q» deng.",
        "ru": "Теперь я слушаю вас. Есть ли у вас вопрос о лечении или лекарствах? Или скажите, что передать вашему врачу. Если вопросов нет, скажите «нет».",
    },
    "ask_more": {"uz": "Yana savolingiz bormi?", "ru": "Есть ли у вас ещё вопросы?"},
    "ask_go": {"uz": "Marhamat, savolingizni ayting.", "ru": "Пожалуйста, говорите, я слушаю."},
    "ask_retry": {
        "uz": "Kechirasiz, eshitmadim. Savolingizni yana bir marta ayting yoki «yo'q» deng.",
        "ru": "Простите, я не расслышала. Повторите вопрос или скажите «нет».",
    },
    # spoken while the answer is being found, so she does not wait in silence
    "ask_wait": {"uz": "Bir soniya, o'ylab ko'ray.", "ru": "Секунду, сейчас отвечу."},
    # the leaflet has no answer, or the question is about her own treatment: it goes to a person
    "ask_doctor": {
        "uz": "Bu savolga shifokoringiz javob bergani ma'qul. Savolingizni unga yetkazdim, u siz bilan bog'lanadi.",
        "ru": "На этот вопрос лучше ответит ваш врач. Я передала ему ваш вопрос, он свяжется с вами.",
    },
    "ask_nurse": {
        "uz": "Bu savolga tibbiyot xodimi javob bergani ma'qul. Savolingizni patronaj hamshirasiga yetkazdim, u siz bilan bog'lanadi.",
        "ru": "На этот вопрос лучше ответит медицинский работник. Я передала ваш вопрос патронажной медсестре, она свяжется с вами.",
    },
    # she named a warning sign: no model is asked, the rules have already raised the alarm
    "ask_alarm": {
        "uz": "Aytganlaringiz xavfli belgi bo'lishi mumkin. Iltimos, kutmasdan bir yuz uch raqamiga qo'ng'iroq qiling. "
        "Shifokoringizga shoshilinch xabar yubordim.",
        "ru": "То, что вы описали, может быть опасным признаком. Пожалуйста, не ждите и позвоните по номеру сто три. "
        "Вашему врачу отправлено срочное сообщение.",
    },
    # after an answer to a question in which she also named a complaint
    "ask_told": {"uz": "Aytganlaringizni shifokoringizga ham yetkazdim.", "ru": "Я также передала ваши слова вашему врачу."},
    # after the greeting: how to reach a person
    "hint": {
        "uz": "Agar shifokor yoki xodim bilan gaplashmoqchi bo'lsangiz, istalgan payt «shifokor» yoki «operator» deng.",
        "ru": "Если захотите поговорить с врачом или сотрудником, в любой момент скажите «врач» или «оператор».",
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
    # she asked for a doctor: the questions stop at once and the doctor is told
    "doctor_ok": {
        "uz": "Tushundim. So'rovingizni hoziroq shifokorga yubordim, u sizga yarim soat ichida qo'ng'iroq qiladi. Ahvolingiz og'irlashsa, bir yuz uch raqamiga qo'ng'iroq qiling.",
        "ru": "Поняла. Я сразу передала вашу просьбу врачу, он перезвонит вам в течение получаса. Если станет хуже, звоните по номеру сто три.",
    },
    "operator_ok": {
        "uz": "Tushundim. Poliklinika xodimi sizga yarim soat ichida qo'ng'iroq qiladi. Ahvolingiz og'irlashsa, bir yuz uch raqamiga qo'ng'iroq qiling.",
        "ru": "Поняла. Сотрудник поликлиники перезвонит вам в течение получаса. Если станет хуже, звоните по номеру сто три.",
    },
}


def say(lang):
    """Every phrase in one language, for the call page."""
    return {key: text.get(lang) or text["uz"] for key, text in SAY.items()}
