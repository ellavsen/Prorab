"""Хендлеры сметы: старт, категория, /new, /estimates, /switch."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from smeta_core import Category, IntegrityError, RateBase, parse_rate, to_bp
from smeta_storage import (
    contract_terms,
    create_estimate,
    current_estimate,
    enforce_retention,
    find_by_number,
    list_estimates,
    newest_estimate,
    set_category,
    set_current_estimate,
    set_rate_base,
    set_rates,
    touch_estimate,
    user_state,
    verified_totals,
)

from ..database import SessionLocal
from ..help_texts import HELP_TEXT, START_TEXT
from ..keyboards import (
    basis_change_keyboard,
    basis_choice_keyboard,
    categories_keyboard,
    mode_keyboard,
    renew_keyboard,
    start_keyboard,
)
from ..texts import (
    BASIS_SHOWN,
    BASIS_UNCLEAR,
    CATEGORY_LABEL,
    INHERITED,
    INTEGRITY_BROKEN,
    basis_effect,
    basis_example,
    basis_question,
    describe_version,
    esc,
    markup_caption,
    render_rates,
    render_summary,
)


async def start(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        START_TEXT, reply_markup=start_keyboard(), parse_mode=ParseMode.HTML
    )


async def help_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=start_keyboard()
    )


async def handle_begin(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    with SessionLocal() as db:
        set_category(db, update.effective_user.id, None)
    await update.message.reply_text(
        "Выбери категорию: «Работа» или «Материал».", reply_markup=categories_keyboard()
    )


async def handle_category(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip().lower()
    category = Category.WORK if text == "работа" else Category.MATERIAL
    with SessionLocal() as db:
        set_category(db, update.effective_user.id, category)

    await update.message.reply_text(
        f"Активная категория: <b>{CATEGORY_LABEL[category]}</b> ✅\nКак вводим?",
        parse_mode=ParseMode.HTML,
        reply_markup=mode_keyboard(),
    )


RATE_TARGETS = {
    "работы": "work",
    "работа": "work",
    "материалы": "material",
    "материал": "material",
}


async def cmd_rate(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """/rate 6 — обе ставки; /rate работы 10 — только работы; /rate — показать.

    Меняет ставку ТОЛЬКО активной сметы: ставка — часть документа, и уже
    выставленные сметы от этого не меняются (ADR-003).
    """
    args = (update.message.text or "").split()[1:]
    uid = update.effective_user.id

    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        if not args:
            await update.message.reply_text(
                render_rates(estimate, verified_totals(db, estimate)),
                parse_mode=ParseMode.HTML,
            )
            return

        target = "both"
        if args[0].lower() in RATE_TARGETS:
            target = RATE_TARGETS[args[0].lower()]
            args = args[1:]
        if not args:
            await update.message.reply_text("Не указано значение. Пример: /rate работы 10")
            return

        try:
            rate_bp = to_bp(parse_rate(args[0]))
        except ValueError as error:
            await update.message.reply_text(
                f"{esc(error)}\nПример: <code>/rate 6</code>", parse_mode=ParseMode.HTML
            )
            return

        set_rates(
            db, estimate,
            work_bp=rate_bp if target in ("both", "work") else estimate.markup_work_bp,
            material_bp=rate_bp if target in ("both", "material") else estimate.markup_material_bp,
        )
        await update.message.reply_text(
            render_rates(estimate, verified_totals(db, estimate)),
            parse_mode=ParseMode.HTML,
        )


BASIS_ARGS = {
    "к цене": RateBase.COST,
    "от суммы": RateBase.PRICE,
}


async def cmd_basis(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """/basis — показать; /basis к цене | от суммы — поменять.

    Отдельной командой, а не аргументом /rate: ставку жмут часто и не глядя, а
    основание меняют раз в договор. Аргументы — те же два слова, что человек
    видел на кнопке, ничего нового запоминать не нужно.
    """
    argument = " ".join((update.message.text or "").split()[1:]).strip().lower()
    uid = update.effective_user.id

    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        if argument:
            chosen = BASIS_ARGS.get(argument)
            if chosen is None:
                await update.message.reply_text(BASIS_UNCLEAR)
                return
            set_rate_base(db, estimate, chosen)

        other = next(word for word, base in BASIS_ARGS.items()
                     if base != RateBase(estimate.rate_base))
        await update.message.reply_text(
            BASIS_SHOWN.format(
                number=estimate.number, name=esc(estimate.name),
                caption=markup_caption(estimate),
                effect=basis_effect(estimate.rate_base), other=other,
            ),
            parse_mode=ParseMode.HTML,
        )


async def cmd_new(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    parts = (update.message.text or "").strip().split(" ", 1)
    custom_name = parts[1].strip() if len(parts) > 1 else None

    with SessionLocal() as db:
        # Прошлая смета читается ДО создания новой, иначе «прошлой» окажется
        # она сама. Наследуются ставки и основание разом: это условия одного
        # договора, и разъехаться они не должны (contract_terms).
        previous = newest_estimate(db, uid)
        estimate = create_estimate(db, uid, name=custom_name, **contract_terms(previous))
        set_current_estimate(db, uid, estimate.id)
        enforce_retention(db, uid)
        inherited = None if previous is None else INHERITED.format(
            caption=markup_caption(estimate), number=previous.number
        )

    await update.message.reply_text(
        f"Создана и активирована <b>Смета №{estimate.number}</b> — {esc(estimate.name)}",
        parse_mode=ParseMode.HTML,
        reply_markup=categories_keyboard(),
    )
    # Вторым сообщением, потому что клавиатура категорий и инлайн-кнопка не
    # живут на одном сообщении, а категории на /new нужны как раньше.
    if inherited is None:
        await update.message.reply_text(
            basis_question(first=True), parse_mode=ParseMode.HTML,
            reply_markup=basis_choice_keyboard(
                basis_example(RateBase.COST), basis_example(RateBase.PRICE)
            ),
        )
    else:
        await update.message.reply_text(
            inherited, reply_markup=basis_change_keyboard()
        )


async def cmd_estimates(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    with SessionLocal() as db:
        estimates = list_estimates(db, uid)
        if not estimates:
            await update.message.reply_text("У тебя пока нет смет. Создай: /new")
            return

        active_id = user_state(db, uid).current_estimate_id
        # Итог считает домен, у отправленной — после сверки со слепком.
        # Денежных агрегатов в SQL нет: они дают другой ответ, чем /list и
        # Excel (ADR-002).
        #
        # Отказ здесь ловится построчно, а не общим перехватом: одна битая
        # смета не должна прятать остальные четыре.
        summaries = []
        for estimate in estimates:
            try:
                totals = verified_totals(db, estimate)
            except IntegrityError as error:
                summaries.append((estimate, None, estimate.id == active_id, error))
                continue
            summaries.append((estimate, totals, estimate.id == active_id, None))

    for estimate, totals, is_active, error in summaries:
        text = (
            render_summary(estimate, totals, is_active) if error is None
            else f"№{estimate.number}, {describe_version(estimate)}\n"
                 f"{estimate.name}\n{INTEGRITY_BROKEN.format(reason=error)}"
        )
        await update.message.reply_text(
            text, reply_markup=renew_keyboard(estimate.id, estimate.number)
        )


async def cmd_switch(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    args = (update.message.text or "").split()
    if len(args) < 2:
        await update.message.reply_text("Использование: /switch N (номер сметы)")
        return
    try:
        number = int(args[1])
    except ValueError:
        await update.message.reply_text("Номер сметы должен быть числом. Пример: /switch 3")
        return

    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = find_by_number(db, uid, number)
        if estimate is None:
            await update.message.reply_text(f"Смета №{number} не найдена. Посмотри /estimates")
            return
        set_current_estimate(db, uid, estimate.id)
        touch_estimate(db, estimate)

    # Редакция и статус называются прямо: /switch попадает на действующую
    # версию, и человек должен видеть, черновик это или уже отправленный
    # документ — иначе следующая же позиция упрётся в охрану без объяснения.
    await update.message.reply_text(
        f"Переключился на <b>Смета №{number}</b>, {describe_version(estimate)}\n"
        f"{esc(estimate.name)}",
        parse_mode=ParseMode.HTML,
        reply_markup=categories_keyboard(),
    )
