import argparse
import functools
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable

import markdown2 as mk2
import pandas as pd
import psutil
import requests
import schedule

markdown = lambda x: mk2.markdown(
    x, extras=["fenced-code-blocks", "code-friendly", "tables", "cuddled-lists"]
)

logging.basicConfig(level=logging.WARNING)


def find_procs_by_name(name):
    for p in psutil.process_iter(["name"]):
        if re.search(name, p.info["name"], re.IGNORECASE):
            return True
    return False


def log(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        s = time.perf_counter()
        res = func(*args, **kwargs)
        print(f"{func.__name__} elapsed time:{time.perf_counter() - s}")
        return res

    return wrapper


class SYAK:
    def __init__(self, SiYuan_PATH, SiYuan_Port, Anki_Port, Anki_Model):
        self._SiYuan_PATH = SiYuan_PATH
        self._SiYuan_DB_PATH = Path(SiYuan_PATH, "temp", "siyuan.db")
        self._SiYuan_ASSETS_PATH = Path(SiYuan_PATH, "data", "assets")
        self._SiYuan_URL = f"http://localhost:{SiYuan_Port}"
        self._Anki_URL = f"http://localhost:{Anki_Port}"
        self._Anki_MODEL = Anki_Model
        self.modle_fields = [
            "front",
            "back",
            "id",
            "parent_id",
            "hpath",
            "hash",
            "updated",
            "parent_updated",
            "parent_hash",
            "deck",
        ]
        self._Anki_MODEL_CONFIG = {
            "modelName": self._Anki_MODEL,
            "inOrderFields": self.modle_fields,
            "cardTemplates": [
                {
                    "Front": "{{front}}",
                    "Back": "{{FrontSide}}\n\n<hr id=answer>\n\n{{back}}",
                }
            ],
        }
        self._media_regex = r"(?<=\(assets\/)[\w-]*\d{14}-\S{7}\.[\w]+(?=\))"
        self._assets_regex = r"(?<=\()assets\/(?=[\w-]*\d{14}-\S{7}\.[\w]+\))"
        self._ial_regex = r"{:[^\}]*\"}"
        self._inline_eq_regex = r"(?<![\\\&])\$([^\$]+)\$(?!\$)"
        self._eq_regex = r"(?<![\\])\$\$([^\$]+)\$\$"
        self._sy_link_regex = r"(?<![\\])\(\((\d{14}-\S{7})\ [\'\"]([^\'\"]+)[\'\"]\)\)"
        self.summary = []

        self.con = sqlite3.connect(self._SiYuan_DB_PATH)
        self.actions_json = {}
        pass

    def check_procs(self):
        return find_procs_by_name("anki") & find_procs_by_name("siyuan")

    def check_anki_model(self):
        resp = requests.post(
            self._Anki_URL, json={"action": "modelNames", "version": 6}
        )
        exist_models = pd.Series(resp.json()["result"], name="Anki_model")

        if self._Anki_MODEL not in exist_models.values:
            logging.warning("Anki model do not exists.")
            resp = requests.post(
                self._Anki_URL,
                json={
                    "action": "createModel",
                    "version": 6,
                    "params": self._Anki_MODEL_CONFIG,
                },
            )
            if resp.status_code == 200:
                logging.info("Anki model created.")
            else:
                logging.error("Anki model created failed.")
                sys.exit(1)

    @log
    def process_invoke(self):
        actions = [
            "createDeck",
            "addNotes",
            "updateNoteFields",
            "storeMediaFile",
            "changeDeck",
            "deleteNotes",
        ]
        for act in actions:
            if act in self.actions_json:
                logging.debug(f"invoke {act}")
                resp = requests.post(self._Anki_URL, json=self.actions_json[act])
                if resp.status_code == 200:
                    logging.info(f"{act}:{resp.json()}")
                else:
                    logging.error(f"{act}:{resp.json()}")
                    return

    def anki_notes(self, model):
        resp = requests.post(
            self._Anki_URL,
            json={
                "action": "findNotes",
                "version": 6,
                "params": {"query": f'"note:{model}"'},
            },
        )
        if resp.status_code != 200:
            return
        notes = resp.json()["result"]
        if len(notes) == 0:
            return pd.DataFrame(
                [],
                columns=[
                    "note_id",
                    "id",
                    "note_parent_id",
                    "note_hpath",
                    "note_hash",
                    "note_updated",
                    "note_parent_updated",
                    "note_parent_hash",
                    "note_deck",
                    "cards",
                ],
            )
        resp = requests.post(
            self._Anki_URL,
            json={
                "action": "notesInfo",
                "version": 6,
                "params": {
                    "notes": notes,
                },
            },
        )
        notes_info = resp.json()["result"]
        exist = list(
            map(
                lambda x: {
                    "note_id": x["noteId"],
                    "id": x["fields"]["id"]["value"],
                    "note_parent_id": x["fields"]["parent_id"]["value"],
                    "note_hpath": x["fields"]["hpath"]["value"],
                    "note_hash": x["fields"]["hash"]["value"],
                    "note_updated": x["fields"]["updated"]["value"],
                    "note_parent_updated": x["fields"]["parent_updated"]["value"],
                    "note_parent_hash": x["fields"]["parent_hash"]["value"],
                    "note_deck": x["fields"]["deck"]["value"],
                    "cards": x["cards"],
                },
                notes_info,
            )
        )
        return pd.DataFrame(exist)

    def create_deck(self, deck: Iterable):
        create_deck_json = list(
            map(
                lambda x: {"action": "createDeck", "version": 6, "params": {"deck": x}},
                deck,
            )
        )
        create_deck_json = {
            "action": "multi",
            "version": 6,
            "params": {"actions": create_deck_json},
        }
        self.actions_json["createDeck"] = create_deck_json
        return create_deck_json

    def get_deck_info(self, deck: pd.DataFrame, preserve_deck="(default)"):
        query_deck_json = list(
            map(
                lambda x: {
                    "action": "findCards",
                    "version": 6,
                    "params": {
                        "query": f'"deck:{x}"',
                    },
                },
                deck["deck"],
            )
        )
        query_deck_json = {
            "action": "multi",
            "version": 6,
            "params": {"actions": query_deck_json},
        }
        resp = requests.post(self._Anki_URL, json=query_deck_json)
        deck["count"] = list(map(lambda x: len(x["result"]), resp.json()["result"]))
        del_deck = deck["deck"][deck["count"] == 0].tolist()
        del_deck = list(
            filter(lambda x: not re.match(preserve_deck, x, re.IGNORECASE), del_deck)
        )
        return del_deck

    def delete_decks(self, del_deck):
        delete_decks_json = {
            "action": "deleteDecks",
            "version": 6,
            "params": {
                "decks": del_deck,
                "cardsToo": True,
            },
        }
        resp = requests.post(self._Anki_URL, json=delete_decks_json)
        if resp.status_code == 200:
            logging.info(f"deleteDecks:{resp.json()}")

    def media_from_blocks(self, blocks: pd.DataFrame):
        media = pd.concat(
            [
                blocks["markdown"]
                .str.findall(self._media_regex)
                .explode(ignore_index=True),
                blocks["parent_markdown"]
                .str.findall(self._media_regex)
                .explode(ignore_index=True),
            ]
        )
        media = media.to_frame("filename")
        media.dropna(inplace=True)
        if media.empty:
            return
        media["path"] = (self._SiYuan_ASSETS_PATH / media["filename"]).astype(str)
        media_json = media.to_dict(orient="records")
        media_json = list(
            map(
                lambda x: {
                    "action": "storeMediaFile",
                    "version": 6,
                    "params": x,
                },
                media_json,
            )
        )
        media_json = {
            "action": "multi",
            "version": 6,
            "params": {"actions": media_json},
        }
        self.actions_json["storeMediaFile"] = media_json
        return media_json

    def merge_parent_blocks(self, blocks):
        parent_ids = tuple(blocks["parent_id"].tolist())
        if len(parent_ids) == 1:
            parent_ids = f'("{parent_ids[0]}")'
        sql = f"select * from blocks where id in {parent_ids} and type in ('l', 'i', 'b', 's')"
        parent = pd.read_sql(sql, self.con)
        parent = parent[["id", "markdown", "updated", "hash"]].rename(
            {
                "id": "parent_id",
                "markdown": "parent_markdown",
                "updated": "parent_updated",
                "hash": "parent_hash",
            },
            axis=1,
        )
        blocks = blocks.merge(parent, "left", on="parent_id")
        blocks.fillna(
            {
                "parent_markdown": "",
                "parent_updated": "",
                "parent_hash": "",
            },
            inplace=True,
        )
        return blocks

    def add_notes(self, create):
        # todo merge series process
        create["front"] = (
            create["markdown"]
            .str.replace("\n\n", "\n")  # remove empty line
            .str.replace(self._assets_regex, "", regex=True)
            .str.replace(self._ial_regex, " ", regex=True)
            .str.replace(
                self._sy_link_regex,
                lambda x: f"[{x.group(2)}](siyuan://blocks/{x.group(1)})",
                regex=True,
            )
            .apply(markdown)
            .str.replace(
                self._inline_eq_regex,
                lambda x: x.group().strip("$").join(["\\(", "\\)"]),
                regex=True,
            )
            .str.replace(
                self._eq_regex,
                lambda x: x.group().strip("$").join(["\\[", "\\]"]),
                regex=True,
            )
            + '<p><a href="siyuan://blocks/'
            + create["id"]
            + '">'
            + "SiYuanURL"
            + "</a></p>"
        )
        create["back"] = (
            create["parent_markdown"]
            .str.replace("\n\n", "\n")  # remove empty line
            .str.replace(self._assets_regex, "", regex=True)
            .str.replace(self._ial_regex, " ", regex=True)
            .str.replace(
                self._sy_link_regex,
                lambda x: f"[{x.group(2)}](siyuan://blocks/{x.group(1)})",
                regex=True,
            )
            .apply(markdown)
            .str.replace(
                self._inline_eq_regex,
                lambda x: x.group().strip("$").join(["\\(", "\\)"]),
                regex=True,
            )
            .str.replace(
                self._eq_regex,
                lambda x: x.group().strip("$").join(["\\[", "\\]"]),
                regex=True,
            )
        )
        notes = create[self.modle_fields].to_dict(orient="records")
        notes = list(
            map(
                lambda x: {
                    "deckName": x["deck"],
                    "modelName": self._Anki_MODEL,
                    "fields": x,
                },
                notes,
            )
        )
        add_notes_json = {
            "action": "addNotes",
            "version": 6,
            "params": {"notes": notes},
        }
        self.actions_json["addNotes"] = add_notes_json
        return add_notes_json

    def update_notes(self, n):
        n["front"] = (
            n["markdown"]
            .str.replace("\n\n", "\n")  # remove empty line
            .str.replace(self._assets_regex, "", regex=True)
            .str.replace(self._ial_regex, " ", regex=True)
            .str.replace(
                self._sy_link_regex,
                lambda x: f"[{x.group(2)}](siyuan://blocks/{x.group(1)})",
                regex=True,
            )
            .apply(markdown)
            .str.replace(
                self._inline_eq_regex,
                lambda x: x.group().strip("$").join(["\\(", "\\)"]),
                regex=True,
            )
            .str.replace(
                self._eq_regex,
                lambda x: x.group().strip("$").join(["\\[", "\\]"]),
                regex=True,
            )
            + '<p><a href="siyuan://blocks/'
            + n["id"]
            + '">'
            + "SiYuanURL"
            + "</a></p>"
        )
        n["back"] = (
            n["parent_markdown"]
            .str.replace("\n\n", "\n")  # remove empty line
            .str.replace(self._assets_regex, "", regex=True)
            .str.replace(self._ial_regex, " ", regex=True)
            .str.replace(
                self._sy_link_regex,
                lambda x: f"[{x.group(2)}](siyuan://blocks/{x.group(1)})",
                regex=True,
            )
            .apply(markdown)
            .str.replace(
                self._inline_eq_regex,
                lambda x: x.group().strip("$").join(["\\(", "\\)"]),
                regex=True,
            )
            .str.replace(
                self._eq_regex,
                lambda x: x.group().strip("$").join(["\\[", "\\]"]),
                regex=True,
            )
        )
        update_note_fields_json = n[self.modle_fields + ["note_id"]].to_dict(
            orient="records"
        )

        update_note_fields_json = list(
            map(
                lambda x: {
                    "action": "updateNoteFields",
                    "version": 6,
                    "params": {
                        "note": {
                            "id": x.pop("note_id"),
                            "fields": x,
                        }
                    },
                },
                update_note_fields_json,
            )
        )
        update_note_fields_json = {
            "action": "multi",
            "version": 6,
            "params": {"actions": update_note_fields_json},
        }
        self.actions_json["updateNoteFields"] = update_note_fields_json
        return update_note_fields_json

    def update_deck(self, deck: pd.DataFrame):
        # change the oldest card deck
        deck = deck.explode("cards", ignore_index=True)
        deck.sort_values(by=["note_id", "cards"], inplace=True)
        deck = deck.groupby(by=["note_id"], sort=False).first().reset_index()
        deck = deck[["deck", "cards"]].groupby("deck")

        change_deck_json = list(
            map(
                lambda x: {
                    "action": "changeDeck",
                    "version": 6,
                    "params": {
                        "cards": x[1]["cards"].tolist(),
                        "deck": x[0],
                    },
                },
                deck,
            )
        )
        change_deck_json = {
            "action": "multi",
            "version": 6,
            "params": {"actions": change_deck_json},
        }
        self.actions_json["changeDeck"] = change_deck_json
        return change_deck_json

    def delete_notes(self, delete):
        ids = delete["note_id"].tolist()
        delete_notes_json = {
            "action": "deleteNotes",
            "version": 6,
            "params": {"notes": ids},
        }
        self.actions_json["deleteNotes"] = delete_notes_json
        return delete_notes_json

    def send_finish(self, msg=""):
        resp = requests.post(
            self._SiYuan_URL + "/api/notification/pushMsg",
            json={"msg": f"Anki sync finished\n{msg}", "timeout": 5000},
        )
        pass

    @log
    def run(self):
        if not self.check_procs():
            logging.warning("Anki/SiYuan not running!")
            return

        # get SiYuan notebooks
        resp = requests.post(
            self._SiYuan_URL + "/api/notebook/lsNotebooks",
        )
        sy_notebook = resp.json()["data"]["notebooks"]
        if len(sy_notebook) < 0:
            logging.warning("SiYuan notebooks do not exists.")
            return
        sy_notebook = pd.DataFrame(sy_notebook)[["id", "name"]].rename(
            {"id": "box", "name": "boxName"}, axis=1
        )

        # check Anki model exist
        self.check_anki_model()

        # get Anki decks
        resp = requests.post(self._Anki_URL, json={"action": "deckNames", "version": 6})
        exist_decks = pd.Series(resp.json()["result"], name="deck").to_frame()

        sql = "select * from refs where content like '%card%'"
        refs = pd.read_sql(sql, con=self.con)
        if refs.empty:
            logging.warning("SiYuan does not any card.")
            return
        block_ids = tuple(refs["block_id"].tolist())
        if len(block_ids) == 1:
            block_ids = f'("{block_ids[0]}")'
        sql = f"select * from blocks where id in {block_ids}"
        blocks = pd.read_sql(sql, self.con)
        blocks = blocks.merge(sy_notebook, how="left", on="box")
        blocks["deck"] = (blocks["boxName"] + blocks["hpath"]).str.replace("/", "::")

        exists = self.anki_notes(self._Anki_MODEL)
        delete = exists[~exists["id"].isin(blocks["id"])]
        remain = exists[exists["id"].isin(blocks["id"])]
        create = blocks[~blocks["id"].isin(remain["id"])]

        new_decks = pd.Series([], name="deck", dtype=str)
        media = pd.DataFrame([], columns=["markdown", "parent_markdown"])

        # add params to actions_json for creating notes
        if not create.empty:
            self.summary.append(f"num of create: {len(create)}")
            # when child blocks changed, parent blocks must be updated.
            create = self.merge_parent_blocks(create)
            self.add_notes(create)
            media = pd.concat([media, create[["markdown", "parent_markdown"]]])
            new_decks = pd.concat([new_decks, create["deck"]], ignore_index=True)

        if not remain.empty:
            remain = remain.merge(blocks, how="left", on="id")
            remain = self.merge_parent_blocks(remain)
            # todo only update deck field
            notes_to_update = remain[
                (remain["note_hash"] != remain["hash"])
                | (remain["note_deck"] != remain["deck"])
                | (remain["note_parent_hash"] != remain["parent_hash"])
            ].copy()
            # notes_to_update = remain
            decks_to_update = remain[remain["note_deck"] != remain["deck"]]
            self.summary.append(f"num of update: {len(notes_to_update)}")
            if not notes_to_update.empty:
                self.update_notes(notes_to_update)
                media = pd.concat(
                    [media, notes_to_update[["markdown", "parent_markdown"]]]
                )
            if not decks_to_update.empty:
                self.update_deck(decks_to_update)
                new_decks = pd.concat(
                    [new_decks, decks_to_update["deck"]], ignore_index=True
                )

        # add params to actions_json for deleting notes
        if not delete.empty:
            self.summary.append(f"num of delete: {len(delete)}")
            self.delete_notes(delete)

        # add params to actions_json for creating decks
        new_decks = pd.Series(
            new_decks[~new_decks.isin(exist_decks["deck"])].unique(), name="deck"
        )
        if not new_decks.empty:
            self.create_deck(new_decks)

        # add params to actions_json for adding media
        if not media.empty:
            self.media_from_blocks(media)

        # do all requests
        self.process_invoke()

        # get Anki decks and delete unused decks
        resp = requests.post(self._Anki_URL, json={"action": "deckNames", "version": 6})
        exist_decks = pd.Series(resp.json()["result"], name="deck").to_frame()
        del_deck = self.get_deck_info(exist_decks)
        if del_deck:
            self.delete_decks(del_deck)

        # send finish message to SiYuan
        self.send_finish("\n".join(self.summary))


def main():
    parser = argparse.ArgumentParser(prog="syak", description="Sync SiYuan to Anki")
    parser.add_argument(
        "-p",
        "--path",
        help="path of your SiYuan data",
        dest="SiYuan_data_path",
        required=True,
    )
    parser.add_argument("-i", "--interval", help="interval of sync(seconds)", default=None, type=int)
    parser.add_argument("--SiYuanPort", help="port of SiYuan", default=6806)
    parser.add_argument("--ANKIPort", help="port of Anki", default=8765)
    parser.add_argument(
        "--model", help="model of Anki", default="SiYuanModel", dest="Anki_model"
    )
    args = parser.parse_args()
    path = Path(args.SiYuan_data_path)
    if not path.exists() or not path.is_dir():
        logging.error("SiYuan path does not exists.")
        exit()
    syak = SYAK(args.SiYuan_data_path, args.SiYuanPort, args.ANKIPort, args.Anki_model)
    if args.interval:
        schedule.every(args.interval).seconds.do(syak.run)
        while True:
            schedule.run_pending()
            time.sleep(1)
    else:
        syak.run()
    print("\n".join(syak.summary))


if __name__ == "__main__":
    main()
