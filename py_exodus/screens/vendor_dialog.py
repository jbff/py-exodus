"""Per-class vendor dialogs (port of the Java ``vendor/`` package).

Java truth:
- ``vendor/BaseVendor.java`` — abstract dialog engine, ConvState machine,
  ``checkCanPay`` helpers, gold charged on ``member.getPlayer().gold``.
- ``vendor/FoodVendor.java``, ``vendor/TavernService.java``,
  ``vendor/OracleService.java``, ``vendor/HorseService.java``,
  ``vendor/WeaponVendor.java``, ``vendor/ArmorVendor.java``,
  ``vendor/GuildVendor.java``, ``vendor/HealerService.java`` — one state
  machine per vendor class (all eight Java ``InventoryType`` impls from
  ``VendorClassSet.getVendorImpl``, VendorClassSet.java:58-94).

Driving order mirrors ``exodus/ConversationDialog.java:82-86``: on each user
input the dialog calls ``set_response(input)`` **then** ``next_dialog()``;
the conversation ends when ``next_dialog()`` returns False (Java's terminal
states) or on empty input (Java ``ConversationDialog.java:74-80`` hides the
dialog). Java message strings are preserved verbatim, including quirks
(dead-code branches, the oracle's end-after-purchase return, the horse's
hard-coded "200g.p" line while the item price is 100 from vendor.xml).
"""
from __future__ import annotations

import enum
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py_exodus.entities.defs import VendorDef, VendorItemDef
    from py_exodus.entities.party import PartyMember
    from py_exodus.ui.text_log import TextLog


class ConvState(enum.Enum):
    """Java ``vendor/BaseVendor.java:11-47`` (all states; those Java classes
    never reach — lodging, foggy memory — still have no Python caller)."""

    ASK_BUY = enum.auto()
    ASK_BUY_SELL = enum.auto()
    WAIT_BUY_INPUT = enum.auto()
    WAIT_BUY_ONE = enum.auto()
    WAIT_BUY_HOW_MANY = enum.auto()
    WAIT_YOU_PAY = enum.auto()
    BUY_ITEM = enum.auto()
    ASK_FOOD_ALE = enum.auto()
    BUY_FOOD = enum.auto()
    BUY_ALE = enum.auto()
    BUY_ALE_WITH_TIP = enum.auto()
    DECLINE_BUY = enum.auto()
    ANYTHING_ELSE = enum.auto()
    FAREWELL = enum.auto()
    # Sell flow (WeaponVendor.java / ArmorVendor.java)
    WAIT_SELL_INPUT = enum.auto()
    WAIT_SELL_ONE = enum.auto()
    WAIT_SELL_HOW_MANY = enum.auto()
    WAIT_SELL_DONT_HAVE_THAT_MANY = enum.auto()
    SELL_ITEM = enum.auto()
    # Healer (HealerService.java)
    WAIT_NEED_HELP = enum.auto()
    WAIT_GIVE_BLOOD = enum.auto()
    GIVE_BLOOD = enum.auto()
    WAIT_WHICH_SERVICE = enum.auto()
    WAIT_WHO_SERVICE = enum.auto()
    WAIT_PERFORM_SERVICE = enum.auto()
    PERFORM_SERVICE = enum.auto()


class BaseVendorDialog:
    """Java ``vendor/BaseVendor.java``."""

    def __init__(
        self,
        vendor: VendorDef,
        member: PartyMember,
        text_log: TextLog,
        screen=None,
        on_end: Callable[[], None] | None = None,
    ) -> None:
        self.vendor = vendor
        self.member = member
        self.text_log = text_log
        self.screen = screen
        self.on_end = on_end
        self.type = (vendor.vendor_type or "").upper()

        self.state: ConvState = ConvState.ASK_BUY
        self.welcome_message = "Welcome to %s"
        self.current_selected_item: VendorItemDef | None = None
        self.current_count = 0

    # --- Java BaseVendor.java:130-136 ---
    def display(self, s: str) -> None:
        self.text_log.add_message(s)

    def init(self) -> None:
        """Java ``BaseVendor.init()``; subclasses set state + welcome text."""

    def next_dialog(self) -> bool:
        """Display the current state's messages. Returns False to end."""
        raise NotImplementedError

    def set_response(self, input: str) -> None:
        """Consume the player's input (Java ``BaseVendor.setResponse``)."""
        raise NotImplementedError

    # --- Java BaseVendor.java:81-107 ---
    def check_can_pay(self, item: VendorItemDef | None) -> bool:
        player = self._player()
        if item is None:
            self.display("I cannot help thee with that.")
            self.state = ConvState.ASK_BUY_SELL
            return False
        if item.price > player.gold:
            self.display(self._item_description(item, item.price))
            self.display("You have not the funds for even one!")
            self.state = ConvState.ASK_BUY_SELL
            return False
        if player.gold > item.price * 2:
            self.state = ConvState.WAIT_BUY_HOW_MANY
        else:
            self.state = ConvState.WAIT_BUY_ONE
        return True

    # --- Java BaseVendor.java:109-128 ---
    def check_can_pay_count(self, item: VendorItemDef | None, count: int) -> bool:
        player = self._player()
        if item is None:
            self.display("I cannot help thee with that.")
            self.state = ConvState.ASK_BUY_SELL
            return False
        if item.price * count > player.gold:
            self.display("I fear you have not the funds, perhaps something else.")
            self.state = ConvState.ASK_BUY_SELL
            return False
        self.state = ConvState.BUY_ITEM
        return True

    # --- internals ---------------------------------------------------------

    def _player(self):
        """Java ``PartyMember.getPlayer()``."""
        return getattr(self.member, "player", self.member)

    @staticmethod
    def _item_description(item: VendorItemDef, price: int) -> str:
        """Java ``String.format(item.getDescription(), item.getPrice())``;
        vendor.xml descriptions for priced goods embed the price as %s (or
        %d for the weapon/armor catalogs) — descriptions without a
        placeholder (guild/healer) format to themselves, exactly like Java."""
        desc = getattr(item, "description", None)
        if desc and ("%s" in desc or "%d" in desc):
            return desc % price
        return desc or str(item.name)

    def run(self) -> None:
        """Initial ``vendor.nextDialog()`` (Java ConversationDialog.java:166)
        and the interactive input loop, driven through chained text-log prompts."""
        self.init()
        self._ask()

    def _ask(self) -> None:
        while True:
            if not self.next_dialog():
                self._finish()
                return
            # Java self-transitioning terminal states (e.g. Tavern DECLINE_BUY
            # sets FAREWELL) print through to the farewell in one pass instead
            # of waiting for another input.
            if self.state != ConvState.FAREWELL:
                break
        query, single_char = self._prompt_for_state()
        self.text_log.prompt(query, callback=self._on_input, single_char=single_char)

    def _on_input(self, value: str) -> None:
        if not value:
            # Java ConversationDialog.java:74-80: empty input hides the dialog
            # without consulting the vendor.
            self._finish()
            return
        # Java ConversationDialog.java:85-86: setResponse then nextDialog.
        self.set_response(value)
        self._ask()

    def _prompt_for_state(self) -> tuple[str, bool]:
        return ("Reply?", True)

    def _finish(self) -> None:
        if self.on_end is not None:
            self.on_end()


class FoodVendorDialog(BaseVendorDialog):
    """Java ``vendor/FoodVendor.java``. The FOOD item is found by
    InventoryType, not by choice key (FoodVendor.java:13-17)."""

    def __init__(self, vendor, member, text_log, screen=None, on_end=None) -> None:
        super().__init__(vendor, member, text_log, screen, on_end)
        self.food_item: VendorItemDef | None = None

    def init(self) -> None:
        # Java FoodVendor.java:21-24
        self.welcome_message = "Welcome to %s"
        self.state = ConvState.ASK_BUY
        # Java FoodVendor.java:13-17 — last FOOD-typed item wins.
        for item in self.vendor.items:
            if (item.item_type or "").upper() == "FOOD":
                self.food_item = item

    def next_dialog(self) -> bool:
        # Java FoodVendor.java:27-68
        if self.state == ConvState.ASK_BUY:
            self.display(self.welcome_message % self.vendor.name)
            self.display(f"{self.vendor.owner} says: Good day, and Welcome friend.")
            self.display("May I interest you in some rations?")
        elif self.state == ConvState.WAIT_BUY_HOW_MANY:
            food = self.food_item
            self.display(
                f"We have the best adventure rations, {food.quantity}"
                f" for only {food.price}gp."
            )
            self.display(f"How many packs of {food.quantity} would you like?")
        elif self.state == ConvState.BUY_FOOD:
            # Java FoodVendor.java:42-48
            self._player().food = self._player().food + (
                self.current_count * self.food_item.quantity
            )
            self._player().adjust_gold(-self.food_item.price * self.current_count)
            self.display("Thank you.")
            self.display("Anything else?")
            self.state = ConvState.ANYTHING_ELSE
        elif self.state == ConvState.ANYTHING_ELSE:
            self.display("Anything else?")
        elif self.state == ConvState.DECLINE_BUY:
            self.display("Too bad. Maybe next time.")
            self.state = ConvState.FAREWELL
        elif self.state == ConvState.FAREWELL:
            self.display("Goodbye. Come again!")
            return False
        else:
            self.display("I cannot help you with that.")
            self.state = ConvState.ANYTHING_ELSE
        return True

    def set_response(self, input: str) -> None:
        inp = (input or "").lower()
        # Java FoodVendor.java:72-97
        if self.state in (ConvState.ASK_BUY, ConvState.ANYTHING_ELSE):
            if inp.startswith("y"):
                self.state = ConvState.WAIT_BUY_HOW_MANY
            else:
                self.state = ConvState.FAREWELL
        elif self.state == ConvState.WAIT_BUY_HOW_MANY:
            try:
                count = int(inp)
            except ValueError:
                count = 1
            self.current_count = count
            if self.current_count == 0 or not self._check_can_pay_food():
                self.state = ConvState.FAREWELL
            else:
                self.state = ConvState.BUY_FOOD

    def _check_can_pay_food(self) -> bool:
        # Java FoodVendor.java:101-112 (integer-division parity)
        player = self._player()
        if self.food_item.price * self.current_count > player.gold:
            self.display(
                f"You can only afford {player.gold // self.food_item.price} packs."
            )
            return False
        return True

    def _prompt_for_state(self) -> tuple[str, bool]:
        if self.state == ConvState.WAIT_BUY_HOW_MANY:
            return ("How many packs?", False)
        return ("Reply? (y or n)", True)


class TavernVendorDialog(BaseVendorDialog):
    """Java ``vendor/TavernService.java``. The specialty food item is matched
    by name against ``genericField1`` (TavernService.java:15-27)."""

    def __init__(self, vendor, member, text_log, screen=None, on_end=None) -> None:
        super().__init__(vendor, member, text_log, screen, on_end)
        self.you_pay = 0
        self.tip = 0
        self.spec_food: VendorItemDef | None = None
        self.ale: VendorItemDef | None = None

    def init(self) -> None:
        # Java TavernService.java:30-33
        self.welcome_message = "%s says: Welcome to %s"
        self.state = ConvState.ASK_FOOD_ALE
        for item in self.vendor.items:
            if (item.item_type or "").upper() == "FOOD":
                if item.name == (self.vendor.generic_field1 or ""):
                    self.spec_food = item
                else:
                    self.ale = item

    def next_dialog(self) -> bool:
        # Java TavernService.java:36-103
        if self.state == ConvState.ASK_FOOD_ALE:
            self.display(
                self.welcome_message % (self.vendor.owner, self.vendor.name)
            )
            self.display("What'll it be, Food er Ale? ")
        elif self.state == ConvState.WAIT_BUY_HOW_MANY:
            self.display(
                f"Our specialty is {self.vendor.generic_field1}"
                f" which costs {self.spec_food.price}gp."
            )
            self.display("How many plates would you like?")
        elif self.state == ConvState.BUY_FOOD:
            # Java TavernService.java:51-58: a plate is one food; there is no
            # affordability check on the food path (Java 132-138 is dead code).
            self._player().food = self._player().food + self.current_count
            self._player().adjust_gold(-self.spec_food.price * self.current_count)
            self.display("Here ye arr.")
            self.display("Somethin' else?")
            self.state = ConvState.ANYTHING_ELSE
        elif self.state == ConvState.WAIT_YOU_PAY:
            self.display(
                f"Here's a mug of our best. That'll be {self.ale.price}gp."
            )
            self.display("You pay?")
        elif self.state == ConvState.BUY_ALE:
            self._player().adjust_gold(-self.you_pay)
            self.display("Here ye arr.")
            self.display("Somethin' else?")
            self.state = ConvState.ANYTHING_ELSE
        elif self.state == ConvState.BUY_ALE_WITH_TIP:
            self._player().adjust_gold(-self.you_pay)
            self.display("Here ye arr.")
            item = self._get_tavern_info(self.tip)
            if item is not None:
                self.display(self._clue_text(item, self.vendor.owner))
            else:
                self.display("Thank you kindly.")
            self.display("Somethin' else?")
            self.state = ConvState.ANYTHING_ELSE
        elif self.state == ConvState.ANYTHING_ELSE:
            self.display("Somethin' else?")
        elif self.state == ConvState.DECLINE_BUY:
            # Java TavernService.java:88-91
            self.display("Won't pay, eh. Ya scum, be gone fore ey call the guards!")
            self.state = ConvState.FAREWELL
        elif self.state == ConvState.FAREWELL:
            self.display("See ya mate!")
            return False
        else:
            self.display("I cannot help ya with that.")
            self.state = ConvState.ANYTHING_ELSE
        return True

    def set_response(self, input: str) -> None:
        inp = (input or "").lower()
        # Java TavernService.java:106-173
        if self.state in (ConvState.ASK_FOOD_ALE, ConvState.ANYTHING_ELSE):
            if inp.startswith("f"):
                self.state = ConvState.WAIT_BUY_HOW_MANY
            elif inp.startswith("a"):
                self.state = ConvState.WAIT_YOU_PAY
            elif inp.startswith("y"):
                self.state = ConvState.ASK_FOOD_ALE
            else:
                self.state = ConvState.FAREWELL
        elif self.state == ConvState.WAIT_BUY_HOW_MANY:
            try:
                count = int(inp)
            except ValueError:
                count = 1
            self.current_count = count
            if self.current_count == 0:
                self.state = ConvState.FAREWELL
            else:
                self.state = ConvState.BUY_FOOD
        elif self.state == ConvState.WAIT_YOU_PAY:
            amnt = self.ale.price
            try:
                amnt = int(inp)
            except ValueError:
                pass
            self.you_pay = amnt
            self.tip = amnt - self.ale.price
            if not self._check_can_pay_ale():
                self.state = ConvState.FAREWELL
            elif self.you_pay < self.ale.price:
                self.state = ConvState.DECLINE_BUY
            elif self.you_pay == 1:
                # Java TavernService.java:157-158: silent farewell edge.
                self.state = ConvState.FAREWELL
            elif self.you_pay == self.ale.price:
                self.state = ConvState.BUY_ALE
            elif self.you_pay > self.ale.price:
                self.state = ConvState.BUY_ALE_WITH_TIP

    # --- Java TavernService.java:175-184 ------------------------------------
    def _get_tavern_info(self, tip: int) -> VendorItemDef | None:
        for item in self.vendor.items:
            if (item.item_type or "").upper() == "TAVERNINFO" and tip // 10 == item.price // 10:
                return item
        return None

    # --- Java TavernService.java:186-210 ------------------------------------
    def _check_can_pay_ale(self) -> bool:
        player = self._player()
        if self.ale.price + self.tip > player.gold:
            self.display("It seems that you have not the gold. Good Day!")
            return False
        return True

    @staticmethod
    def _clue_text(item: VendorItemDef, owner: str) -> str:
        """Java ``String.format(item.getDescription(), vendor.getOwner())``
        (TavernService.java:77)."""
        desc = item.description or ""
        if "%s" in desc:
            return desc % owner
        return desc

    def _prompt_for_state(self) -> tuple[str, bool]:
        if self.state == ConvState.WAIT_BUY_HOW_MANY:
            return ("How many plates?", False)
        if self.state == ConvState.WAIT_YOU_PAY:
            return ("You pay?", False)
        if self.state in (ConvState.ASK_FOOD_ALE, ConvState.ANYTHING_ELSE):
            return ("Food er Ale? (f, a or n)", True)
        return ("Reply?", True)


class OracleVendorDialog(BaseVendorDialog):
    """Java ``vendor/OracleService.java``."""

    def __init__(self, vendor, member, text_log, screen=None, on_end=None) -> None:
        super().__init__(vendor, member, text_log, screen, on_end)
        self.you_pay = 0

    def init(self) -> None:
        # Java OracleService.java:24-28
        self.welcome_message = "%s:\nProphet of Life!"
        self.state = ConvState.WAIT_BUY_INPUT

    def next_dialog(self) -> bool:
        # Java OracleService.java:31-55
        if self.state == ConvState.WAIT_BUY_INPUT:
            self.display(self.welcome_message % self.vendor.owner)
            self.display("How may 100 gp is your offering?")
        elif self.state == ConvState.ANYTHING_ELSE:
            self.display("More offering?")
        elif self.state == ConvState.BUY_ITEM:
            # Java OracleService.java:40-48: adjustGold(-currentCount) with
            # currentCount being the absolute gp amount; nextDialog returns
            # False after a purchase (oracle speaks once per visit).
            self._player().adjust_gold(-self.current_count)
            item = self._get_oracle_info(self.current_count)
            if item is not None:
                self.display(self._clue_text(item, self.vendor.owner))
            self.display("More offering?")
            self.state = ConvState.ANYTHING_ELSE
            return False
        else:
            # Java default case (covers FAREWELL OracleService.java:50)
            self.display("Fare thee well and good luck!")
            return False
        return True

    def set_response(self, input: str) -> None:
        inp = (input or "").lower()
        # Java OracleService.java:58-86
        if self.state == ConvState.WAIT_BUY_INPUT:
            offering = 1
            try:
                offering = int(inp)
            except ValueError:
                offering = 1
            self.current_count = offering * 100
            if not self._check_can_pay(self.current_count):
                self.state = ConvState.ANYTHING_ELSE
                return
            self.state = ConvState.BUY_ITEM
        elif self.state == ConvState.ANYTHING_ELSE:
            if inp.startswith("y"):
                self.state = ConvState.WAIT_BUY_INPUT
            else:
                self.state = ConvState.FAREWELL

    # --- Java OracleService.java:88-115 -------------------------------------
    def _get_oracle_info(self, amt: int) -> VendorItemDef | None:
        for item in self.vendor.items:
            if (item.item_type or "").upper() == "ORACLEINFO" and amt == item.price:
                return item
        return None

    def _check_can_pay(self, amt: int) -> bool:
        if amt == 0:
            self.display(
                "And so the sage said unto thee, if thou can solve my rhyme.."
            )
            return False
        if amt > self._player().gold:
            self.display("It seems thou hast not gold enough to pay!")
            return False
        return True

    @staticmethod
    def _clue_text(item: VendorItemDef, owner: str) -> str:
        desc = item.description or ""
        if "%s" in desc:
            return desc % owner
        return desc

    def _prompt_for_state(self) -> tuple[str, bool]:
        if self.state == ConvState.WAIT_BUY_INPUT:
            return ("Your offering? (in 100 gp units)", False)
        return ("More offering? (y or n)", True)


class HorseVendorDialog(BaseVendorDialog):
    """Java ``vendor/HorseService.java``. The horse item is keyed by the
    ``choice`` "y" (HorseService.java:69)."""

    def init(self) -> None:
        # Java HorseService.java:16-19 — the format arguments are ignored for
        # the constant welcome message.
        self.welcome_message = "Welcome friend!"
        self.state = ConvState.WAIT_BUY_INPUT

    def next_dialog(self) -> bool:
        # Java HorseService.java:23-58
        if self.state == ConvState.WAIT_BUY_INPUT:
            self.display("Welcome friend!")
            self.display("Can I interest thee in horses?")
        elif self.state == ConvState.WAIT_BUY_ONE:
            # Java HorseService.java:30-32: "200g.p" is hard-coded by Java.
            self.display("For only 200g.p thou can have the best. Wilt thou buy?")
        elif self.state == ConvState.BUY_ITEM:
            # Java HorseService.java:33-44
            self._player().adjust_gold(-self.current_selected_item.price)
            self.display("Here, a better breed thou shalt not find ever!")
            if self.screen is not None:
                x, y = self.screen.get_current_map_coords()
                self.screen.add_creature({"tile": "horse", "x": x, "y": y})
                self.screen.board(x, y)
            return False
        elif self.state == ConvState.DECLINE_BUY:
            self.display("A shame, thou looks like thou could use a good horse!")
            return False
        elif self.state == ConvState.FAREWELL:
            self.display("Fare thee well!")
            return False
        else:
            self.display("I cannot help thee with that.")
            self.state = ConvState.WAIT_BUY_INPUT
        return True

    def set_response(self, input: str) -> None:
        inp = (input or "").lower()
        # Java HorseService.java:61-85
        if self.state == ConvState.WAIT_BUY_INPUT:
            if inp.startswith("y"):
                self.state = ConvState.WAIT_BUY_ONE
            else:
                self.state = ConvState.DECLINE_BUY
        elif self.state == ConvState.WAIT_BUY_ONE:
            item = self.vendor.get_item("y")
            self.current_selected_item = item
            if inp.startswith("y") and self._check_can_pay(item):
                self.state = ConvState.BUY_ITEM
            else:
                self.state = ConvState.FAREWELL

    # --- Java HorseService.java:87-103 --------------------------------------
    def _check_can_pay(self, item: VendorItemDef | None) -> bool:
        if item is None:
            self.display("I cannot help thee with that.")
            return False
        if item.price > self._player().gold:
            self.display("It seems thou hast not gold enough to pay!")
            return False
        return True

    def _prompt_for_state(self) -> tuple[str, bool]:
        return ("Reply (y or n)", True)


def _typed_key(enum_cls, raw: object):
    """Key a member's weapons/armors dict: enum member when `raw` names one
    (vendor.xml weaponType/armorType strings match the Java enum names), the
    raw string otherwise — so lookups land on the Character's own buckets."""
    if isinstance(raw, enum_cls):
        return raw
    if raw is not None:
        try:
            return enum_cls[str(raw).upper()]
        except KeyError:
            return raw
    return raw


class BuySellVendorDialog(BaseVendorDialog):
    """The ASK_BUY_SELL machine shared by ``vendor/WeaponVendor.java`` and
    ``vendor/ArmorVendor.java`` — the two classes are line-for-line identical
    except for the inventory array they touch and one display quirk (Armor's
    WAIT_BUY_ONE prints only "Take it?", Weapon prints the description too).
    Buying credits the member's own weapon/armor list and debits the member's
    purse (`adjust_gold`); selling credits `member.gold` with the direct
    Java write ``gold = gold + (price / 2) * count`` (NOT adjustGold, so no
    9999 clamp) and removes the units from the same list. The sell menu lists
    the FULL vendor-class catalog (`vendor.getVendorClass()
    .getItemCatalog()`), filtered to items the member owns."""

    #: Java WeaponVendor.java:52-55 prints the description before "Take it?";
    #: ArmorVendor.java:57 does not (only "Take it?").
    _buy_one_shows_description = False

    def init(self) -> None:
        # Java WeaponVendor.java:19 / ArmorVendor.java:16
        self.welcome_message = (
            "Welcome to %s\n%s says:\nWelcome friend!\nArt thou here to Buy or Sell?"
        )
        self.state = ConvState.ASK_BUY_SELL

    # --- subclass hooks (weapon list vs armor list) -------------------------
    def _unit_key(self, item: VendorItemDef):
        raise NotImplementedError

    def _count_bucket(self) -> dict:
        raise NotImplementedError

    # --- common machine -----------------------------------------------------
    def _owned(self, item: VendorItemDef) -> int:
        return self._count_bucket().get(self._unit_key(item), 0)

    def _sell_catalog(self) -> list[VendorItemDef]:
        """Java ``vendor.getVendorClass().getItemCatalog()`` (full catalog);
        vendors without a wired class fall back to their own items."""
        cls = getattr(self.vendor, "vendor_class", None)
        return list(cls.item_catalog) if cls is not None else list(self.vendor.items)

    def _catalog_item_for_choice(self, choice: str) -> VendorItemDef | None:
        """Java ``vendor.getVendorClass().getItemForChoice(input)``."""
        cls = getattr(self.vendor, "vendor_class", None)
        if cls is not None:
            return cls.get_item(choice)
        return self.vendor.get_item(choice)

    def next_dialog(self) -> bool:
        if self.state == ConvState.ASK_BUY_SELL:
            self.display(
                self.welcome_message % (self.vendor.name, self.vendor.owner)
            )
        elif self.state == ConvState.WAIT_BUY_INPUT:
            # Java WeaponVendor.java:34-45
            list_str = "Very Good!\nWe Have:\n"
            for item in self.vendor.items:
                list_str += f"{item.choice.upper()} - {item.name} for {item.price}gp.\n"
            list_str += "Your Interest?"
            self.display(list_str)
        elif self.state == ConvState.WAIT_BUY_HOW_MANY:
            self.display(
                self._item_description(
                    self.current_selected_item, self.current_selected_item.price
                )
            )
            self.display("How many would you like?")
        elif self.state == ConvState.WAIT_BUY_ONE:
            if self._buy_one_shows_description:
                self.display(
                    self._item_description(
                        self.current_selected_item, self.current_selected_item.price
                    )
                )
            self.display("Take it?")
        elif self.state == ConvState.BUY_ITEM:
            # Java WeaponVendor.java:62-68
            bucket = self._count_bucket()
            key = self._unit_key(self.current_selected_item)
            bucket[key] = bucket.get(key, 0) + self.current_count
            self._player().adjust_gold(
                -self.current_selected_item.price * self.current_count
            )
            self.display(f"{self.vendor.owner} says: A fine choice! anything else?")
        elif self.state == ConvState.WAIT_SELL_INPUT:
            # Java WeaponVendor.java:69-83 — full class catalog, owned only
            sell_list = "Excellent!\n"
            for item in self._sell_catalog():
                count = self._owned(item)
                if count > 0:
                    sell_list += (
                        f"{item.choice.upper()} - {item.name}"
                        f" for {item.price // 2}gp. ({count})\n"
                    )
            sell_list += "Which wouldst you sell?"
            self.display(sell_list)
        elif self.state == ConvState.WAIT_SELL_HOW_MANY:
            self.display(
                f"I will give you {self.current_selected_item.price // 2}gp each."
            )
            self.display("How many would thee like to sell?")
        elif self.state == ConvState.WAIT_SELL_ONE:
            self.display(
                f"I will give you {self.current_selected_item.price // 2}gp for that"
                f" {self.current_selected_item.name}. Deal?"
            )
        elif self.state == ConvState.WAIT_SELL_DONT_HAVE_THAT_MANY:
            self.display("You don't have that many swine! Anything else?")
            self.state = ConvState.ASK_BUY_SELL
        elif self.state == ConvState.SELL_ITEM:
            # Java WeaponVendor.java:99-106 — direct gold write, no clamp
            bucket = self._count_bucket()
            key = self._unit_key(self.current_selected_item)
            bucket[key] = bucket.get(key, 0) - self.current_count
            player = self._player()
            player.gold = player.gold + (
                self.current_selected_item.price // 2
            ) * self.current_count
            self.display("Fine! Anything else?")
        elif self.state == ConvState.FAREWELL:
            self.display(f"{self.vendor.owner} says: Fare thee well!")
            return False
        else:
            self.display("I cannot help thee with that.")
            self.state = ConvState.ASK_BUY_SELL
        return True

    def set_response(self, input: str) -> None:
        inp = (input or "").lower()
        if self.state == ConvState.ASK_BUY_SELL:
            if inp.startswith("b"):
                self.state = ConvState.WAIT_BUY_INPUT
            elif inp.startswith("s"):
                self.state = ConvState.WAIT_SELL_INPUT
            # else: stays ASK_BUY_SELL (Java's empty else)
        elif self.state == ConvState.WAIT_BUY_INPUT:
            item = self.vendor.get_item(inp)
            if item is not None and self.check_can_pay(item):
                self.current_selected_item = item
        elif self.state == ConvState.WAIT_BUY_HOW_MANY:
            try:
                count = int(inp)
            except ValueError:
                count = 1
            if self.check_can_pay_count(self.current_selected_item, count):
                self.current_count = count
            else:
                self.current_count = 0
        elif self.state == ConvState.WAIT_BUY_ONE:
            if inp.startswith("y"):
                self.current_count = 1
                self.state = ConvState.BUY_ITEM
            else:
                self.current_count = 0
                self.state = ConvState.ASK_BUY_SELL
        elif self.state == ConvState.BUY_ITEM:
            if inp.startswith("y"):
                self.state = ConvState.ASK_BUY_SELL
            else:
                self.state = ConvState.FAREWELL
        elif self.state == ConvState.WAIT_SELL_INPUT:
            # Java assigns currentSelectedItem even when null
            item = self._catalog_item_for_choice(inp)
            self.current_selected_item = item
            if item is None:
                self.state = ConvState.WAIT_SELL_DONT_HAVE_THAT_MANY
            elif self._owned(item) > 1:
                self.state = ConvState.WAIT_SELL_HOW_MANY
            else:
                self.state = ConvState.WAIT_SELL_ONE
        elif self.state == ConvState.WAIT_SELL_HOW_MANY:
            try:
                count = int(inp)
            except ValueError:
                count = 1
            if self.current_selected_item is not None and count <= self._owned(
                self.current_selected_item
            ):
                self.current_count = count
                self.state = ConvState.SELL_ITEM
            else:
                self.state = ConvState.WAIT_SELL_DONT_HAVE_THAT_MANY
        elif self.state == ConvState.WAIT_SELL_ONE:
            if inp.startswith("y"):
                self.current_count = 1
                self.state = ConvState.SELL_ITEM
            else:
                self.current_count = 0
                self.state = ConvState.ASK_BUY_SELL
        elif self.state == ConvState.SELL_ITEM:
            if inp.startswith("y"):
                self.state = ConvState.WAIT_SELL_INPUT
            else:
                self.state = ConvState.FAREWELL

    def _prompt_for_state(self) -> tuple[str, bool]:
        if self.state == ConvState.ASK_BUY_SELL:
            return ("Buy or Sell? (b or s)", True)
        if self.state == ConvState.WAIT_BUY_INPUT:
            return ("Your Interest? (choice letter)", True)
        if self.state == ConvState.WAIT_BUY_HOW_MANY:
            return ("How many would you like?", False)
        if self.state == ConvState.WAIT_SELL_INPUT:
            return ("Which wouldst you sell?", True)
        if self.state == ConvState.WAIT_SELL_HOW_MANY:
            return ("How many would thee like to sell?", False)
        return ("Reply (y or n)", True)


class WeaponVendorDialog(BuySellVendorDialog):
    """Java ``vendor/WeaponVendor.java``."""

    _buy_one_shows_description = True  # WeaponVendor.java:52-55

    def _unit_key(self, item: VendorItemDef):
        from py_exodus.constants import WeaponType

        return _typed_key(WeaponType, item.weapon_type)

    def _count_bucket(self) -> dict:
        return self._player().weapons


class ArmorVendorDialog(BuySellVendorDialog):
    """Java ``vendor/ArmorVendor.java``."""

    _buy_one_shows_description = False  # ArmorVendor.java:57 — "Take it?" only

    def _unit_key(self, item: VendorItemDef):
        from py_exodus.constants import ArmorType

        return _typed_key(ArmorType, item.armor_type)

    def _count_bucket(self) -> dict:
        return self._player().armors


class GuildVendorDialog(BaseVendorDialog):
    """Java ``vendor/GuildVendor.java``. The check_can_pay override has NO
    state write on the insufficient-funds branch and prints "What? Can't pay!
    Buzz off swine!" before the visit ends; purchases credit the MEMBER's own
    gems/keys/torches/powder fields (Java BUY_ITEM), never a party pool."""

    def init(self) -> None:
        # Java GuildVendor.java:23-27
        self.welcome_message = "Avast ye mate!"
        self.state = ConvState.ASK_BUY

    def next_dialog(self) -> bool:
        # Java GuildVendor.java:29-71
        if self.state == ConvState.ASK_BUY:
            # format() ignores the unused vendor-name argument, as in Java
            self.display("Avast ye mate!")
            self.display(f"Shure ye wishes to buy from ol' {self.vendor.owner}?")
            self.display(f"Welcome to {self.vendor.name}.\nLike to see my goods?")
        elif self.state == ConvState.WAIT_BUY_INPUT:
            self.display(f"{self.vendor.owner} says: Good Mate! Ya see I gots:\n")
            list_str = ""
            for item in self.vendor.items:
                list_str += (
                    f"{item.choice.upper()} - {item.name}"
                    f" ({item.quantity}) for {item.price}gp\n"
                )
            list_str += "Wat'l it be?"
            self.display(list_str)
        elif self.state == ConvState.WAIT_BUY_ONE:
            self.display(
                self._item_description(
                    self.current_selected_item, self.current_selected_item.price
                )
            )
            self.display("Will ya buy?")
        elif self.state == ConvState.BUY_ITEM:
            # Java GuildVendor.java:44-60 — member-level fields
            player = self._player()
            kind = (self.current_selected_item.guild_item_type or "").lower()
            if kind == "gem":
                player.gems += self.current_selected_item.quantity
            elif kind == "key":
                player.keys += self.current_selected_item.quantity
            elif kind == "powder":
                player.powder += self.current_selected_item.quantity
            elif kind == "torch":
                player.torches += self.current_selected_item.quantity
            player.adjust_gold(-self.current_selected_item.price)
            self.display(f"{self.vendor.owner} says: See more?")
            self.state = ConvState.ANYTHING_ELSE
        elif self.state == ConvState.ANYTHING_ELSE:
            self.display(f"{self.vendor.owner} says: See more?")
        elif self.state == ConvState.DECLINE_BUY:
            # Java GuildVendor.java:63-66 (unreachable dead branch — no
            # setResponse path sets DECLINE_BUY — but the strings are kept).
            self.display("Hmmm...Grmbl...")
            self.state = ConvState.FAREWELL
        elif self.state == ConvState.FAREWELL:
            self.display("See ya matie!")
            return False
        else:
            self.display("I cannot help ya with that.")
            self.state = ConvState.ANYTHING_ELSE
        return True

    def set_response(self, input: str) -> None:
        inp = (input or "").lower()
        # Java GuildVendor.java:74-111
        if self.state in (ConvState.ASK_BUY, ConvState.ANYTHING_ELSE):
            if inp.startswith("y"):
                self.state = ConvState.WAIT_BUY_INPUT
            else:
                self.state = ConvState.FAREWELL
        elif self.state == ConvState.WAIT_BUY_INPUT:
            item = self.vendor.get_item(inp)
            if item is not None and self.check_can_pay(item):
                self.current_selected_item = item
                self.state = ConvState.WAIT_BUY_ONE
            else:
                self.state = ConvState.FAREWELL
        elif self.state == ConvState.WAIT_BUY_ONE:
            if inp.startswith("y"):
                self.current_count = 1
                self.state = ConvState.BUY_ITEM
            else:
                self.current_count = 0
                self.state = ConvState.FAREWELL

    # --- Java GuildVendor.java:113-136 ---------------------------------------
    def check_can_pay(self, item: VendorItemDef | None) -> bool:
        if item is None:
            self.display("I cannot help thee with that.")
            self.state = ConvState.ASK_BUY_SELL
            return False
        if item.price > self._player().gold:
            self.display("What? Can't pay! Buzz off swine!")
            return False
        return True

    def _prompt_for_state(self) -> tuple[str, bool]:
        if self.state == ConvState.ASK_BUY or self.state == ConvState.ANYTHING_ELSE:
            return ("Buy? (y or n)", True)
        if self.state == ConvState.WAIT_BUY_INPUT:
            return ("Wat'l it be?", True)
        if self.state == ConvState.WAIT_BUY_ONE:
            return ("Will ya buy? (y or n)", True)
        return ("Reply (y or n)", True)


class HealerVendorDialog(BaseVendorDialog):
    """Java ``vendor/HealerService.java``. The heal itself lives on
    PartyMember.heal (Party.java:381-433); the healer charges NOTHING when
    the heal returns False (HealerService.java:58-64) — the price is debited
    only on success."""

    def init(self) -> None:
        # Java HealerService.java:18-22
        self.welcome_message = (
            "Welcome unto %s\n\n%s says: Peace and Joy be with you friend."
        )
        self.state = ConvState.WAIT_NEED_HELP

    def next_dialog(self) -> bool:
        # Java HealerService.java:24-101
        if self.state == ConvState.WAIT_NEED_HELP:
            self.display(
                self.welcome_message % (self.vendor.name, self.vendor.owner)
            )
            self.display("\nAre you in need of help?")
        elif self.state == ConvState.WAIT_GIVE_BLOOD:
            self.display(
                "Art thou willing to give 100 pts of thy blood to aid others?"
            )
        elif self.state == ConvState.GIVE_BLOOD:
            self._player().hp = self._player().hp - 100
            self.display("Thou art a great help. We are in dire need!")
        elif self.state == ConvState.WAIT_WHICH_SERVICE:
            list_str = "We can perform:\n\n"
            for item in self.vendor.items:
                list_str += f"{item.choice.upper()} - {item.name} for {item.price}gp.\n"
            list_str += "\nYour Need?"
            self.display(list_str)
        elif self.state == ConvState.WAIT_WHO_SERVICE:
            self.display("Who is in need?")
        elif self.state == ConvState.WAIT_PERFORM_SERVICE:
            self.display(
                f"{self.current_selected_item.description} will cost thee"
                f" {self.current_selected_item.price} gp."
            )
            self.display("Wilt thou pay?")
        elif self.state == ConvState.PERFORM_SERVICE:
            # Java HealerService.java:66-88
            party = getattr(self.member, "party", None)
            members = party.members if party is not None else [self.member]
            if self.current_count <= 0 or self.current_count > len(members):
                self.current_count = 1
            pm = members[self.current_count - 1] if members else None
            if pm is None:
                return True  # Java `break`: nothing displayed, state unchanged
            if pm.heal(self.current_selected_item.heal_type):
                self._player().adjust_gold(-self.current_selected_item.price)
                self.display("There you are. Please be more careful next time.")
            else:
                self.display(f"{pm.name}, thou art not in need of such service.")
            self.display("Anything else?")
            self.state = ConvState.ANYTHING_ELSE
        elif self.state == ConvState.FAREWELL:
            self.display(
                f"{self.vendor.owner} says: May thy life be guarded by"
                " the powers of good."
            )
            return False
        else:
            self.display("I cannot help thee with that.")
            self.state = ConvState.WAIT_NEED_HELP
        return True

    def set_response(self, input: str) -> None:
        inp = (input or "").lower()
        # Java HealerService.java:104-141
        if self.state in (ConvState.WAIT_NEED_HELP, ConvState.ANYTHING_ELSE):
            if inp.startswith("y"):
                self.state = ConvState.WAIT_WHICH_SERVICE
            elif self._player().hp >= 400:
                self.state = ConvState.WAIT_GIVE_BLOOD
            else:
                self.state = ConvState.WAIT_NEED_HELP
        elif self.state == ConvState.WAIT_WHICH_SERVICE:
            item = self.vendor.get_item(inp)
            if item is not None and self.check_can_pay(item):
                self.current_selected_item = item
                self.state = ConvState.WAIT_WHO_SERVICE
            else:
                self.state = ConvState.WAIT_NEED_HELP
        elif self.state == ConvState.WAIT_WHO_SERVICE:
            try:
                count = int(inp)
            except ValueError:
                count = 1
            self.current_count = count
            self.state = ConvState.WAIT_PERFORM_SERVICE
        elif self.state == ConvState.WAIT_PERFORM_SERVICE:
            if inp.startswith("y"):
                self.state = ConvState.PERFORM_SERVICE
            else:
                self.state = ConvState.WAIT_NEED_HELP
        elif self.state == ConvState.WAIT_GIVE_BLOOD:
            if inp.startswith("y"):
                self.state = ConvState.GIVE_BLOOD
            else:
                self.state = ConvState.WAIT_NEED_HELP
        elif self.state == ConvState.GIVE_BLOOD:
            if inp.startswith("y"):
                self.state = ConvState.WAIT_NEED_HELP
            else:
                self.state = ConvState.FAREWELL

    # --- Java HealerService.java:143-158 -------------------------------------
    def check_can_pay(self, item: VendorItemDef | None) -> bool:
        if item is None:
            self.display("I cannot help thee with that.")
            self.state = ConvState.ASK_BUY_SELL
            return False
        if item.price > self._player().gold:
            self.display(
                "I see by thy purse that thou hast not enough gold."
                " I cannot aid thee."
            )
            return False
        return True

    def _prompt_for_state(self) -> tuple[str, bool]:
        if self.state in (ConvState.WAIT_NEED_HELP, ConvState.ANYTHING_ELSE):
            return ("In need of help? (y or n)", True)
        if self.state == ConvState.WAIT_WHICH_SERVICE:
            return ("Your Need? (choice letter)", True)
        if self.state == ConvState.WAIT_WHO_SERVICE:
            return ("Who is in need? (member number)", False)
        if self.state == ConvState.WAIT_PERFORM_SERVICE:
            return ("Wilt thou pay? (y or n)", True)
        if self.state == ConvState.WAIT_GIVE_BLOOD:
            return ("Give blood? (y or n)", True)
        if self.state == ConvState.GIVE_BLOOD:
            return ("More help? (y or n)", True)
        return ("Reply (y or n)", True)


#: Java ``VendorClassSet.getVendorImpl`` (vendor/VendorClassSet.java:58-94).
#: All eight Java ``InventoryType`` impls are ported; unknown types still map
#: to None so the town screen keeps its generic-menu fallback.
VENDOR_DIALOG_CLASSES: dict[str, type[BaseVendorDialog]] = {
    "FOOD": FoodVendorDialog,
    "TAVERNINFO": TavernVendorDialog,
    "ORACLEINFO": OracleVendorDialog,
    "HORSE": HorseVendorDialog,
    "WEAPON": WeaponVendorDialog,
    "ARMOR": ArmorVendorDialog,
    "GUILDITEM": GuildVendorDialog,
    "HEALER": HealerVendorDialog,
}


def create_vendor_dialog(
    vendor: VendorDef,
    member: PartyMember,
    text_log: TextLog,
    screen=None,
    on_end: Callable[[], None] | None = None,
) -> BaseVendorDialog | None:
    """Build the per-class dialog impl, or None when not yet ported."""
    vendor_type = (vendor.vendor_type or "").upper()
    cls = VENDOR_DIALOG_CLASSES.get(vendor_type)
    if cls is None:
        return None
    return cls(vendor, member, text_log, screen=screen, on_end=on_end)


def start_vendor_dialog(
    vendor: VendorDef,
    member: PartyMember,
    text_log: TextLog,
    screen=None,
    on_end: Callable[[], None] | None = None,
) -> bool:
    """Open the per-class vendor conversation; False when the vendor class is
    not ported and the caller should fall back to the generic menu."""
    dialog = create_vendor_dialog(vendor, member, text_log, screen=screen, on_end=on_end)
    if dialog is None:
        return False
    dialog.run()
    return True


__all__ = [
    "VENDOR_DIALOG_CLASSES",
    "ArmorVendorDialog",
    "BaseVendorDialog",
    "BuySellVendorDialog",
    "ConvState",
    "FoodVendorDialog",
    "GuildVendorDialog",
    "HealerVendorDialog",
    "HorseVendorDialog",
    "OracleVendorDialog",
    "TavernVendorDialog",
    "WeaponVendorDialog",
    "create_vendor_dialog",
    "start_vendor_dialog",
]
