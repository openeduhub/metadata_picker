import json
import logging
import multiprocessing
import os
import time
from json import JSONDecodeError
from logging import handlers
from queue import Empty

import uvicorn

from app.api import app
from app.communication import ProcessToDaemonCommunication
from lib.config import MESSAGE_CONTENT, LOGFILE_MANAGER, MESSAGE_HEADERS, MESSAGE_HTML
from lib.timing import get_utc_now
from metadata import Metadata
from features.html_based import Advertisement, Tracker, IFrameEmbeddable, ContentSecurityPolicy, Cookies, \
    FanboySocialMedia, FanboyAnnoyance, EasylistGermany, Paywalls
from settings import API_PORT, LOG_LEVEL, LOG_PATH


class Manager:
    metadata_extractors: list = []

    def __init__(self):

        self._create_logger()

        self._create_extractors()

        self._create_api()

        self.run()

    def _create_api(self):
        self.api_to_manager_queue = multiprocessing.Queue()
        self.manager_to_api_queue = multiprocessing.Queue()
        api_process = multiprocessing.Process(
            target=api_server, args=(self.api_to_manager_queue, self.manager_to_api_queue)
        )
        api_process.start()

    def _create_extractors(self):
        extractors = [Advertisement, Tracker, IFrameEmbeddable, ContentSecurityPolicy, Cookies,
                      EasylistGermany, FanboyAnnoyance, FanboySocialMedia, ContentSecurityPolicy, Paywalls]
        for extractor in extractors:
            self.metadata_extractors.append(extractor(self._logger))

    def _create_logger(self):
        self._logger = logging.getLogger(name=LOGFILE_MANAGER)

        self._logger.propagate = True

        self._logger.setLevel(LOG_LEVEL)

        formatter = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s")

        # Convert time to UTC/GMT time
        logging.Formatter.converter = time.gmtime

        # standard log
        dir_path = os.path.dirname(os.path.realpath(__file__))

        data_path = dir_path + "/" + LOG_PATH

        log_15_mb_limit = 1024 * 1024 * 15
        backup_count = 10000

        if not os.path.exists(data_path):
            os.mkdir(data_path, mode=0o755)
        fh = handlers.RotatingFileHandler(filename=f"{data_path}/{LOGFILE_MANAGER}.log", maxBytes=log_15_mb_limit,
                                          backupCount=backup_count)

        fh.setLevel(LOG_LEVEL)
        fh.setFormatter(formatter)

        self._logger.addHandler(fh)

    def get_api_request(self):
        if self.api_to_manager_queue is not None:
            try:
                request = self.api_to_manager_queue.get(block=False, timeout=0.1)
                if isinstance(request, dict):
                    self.handle_content(request)
            except Empty:
                pass

    def setup(self):
        for metadata_extractor in self.metadata_extractors:
            metadata_extractor: Metadata
            metadata_extractor.setup()

    def _extract_meta_data(self, html_content: str, headers: dict):
        data = {}
        for metadata_extractor in self.metadata_extractors:
            extracted_metadata = metadata_extractor.start(html_content, headers)
            data.update(extracted_metadata)

            self._logger.debug(f"Resulting data: {data}")
        return data

    # =========== LOOP ============
    def run(self):

        while True:
            self.get_api_request()
            self._logger.info(f"Current time: {get_utc_now()}")
            time.sleep(1)

    @staticmethod
    def _preprocess_header(header: str) -> dict:
        header = header.replace("b'", "\"").replace("/'", "\"").replace("'", "\"").replace("\"\"", "\"").replace("/\"",
                                                                                                                 "/")

        idx = header.find("b\"")
        if idx >= 0:
            if header[idx - 1] == "[":
                bracket_idx = header[idx:].find("]")
                header = header[:idx] + "\"" \
                         + header[idx + 2:idx + bracket_idx - 2].replace("\"", " ") \
                         + header[idx + bracket_idx - 1:]

        header = json.loads(header)
        return header

    def handle_content(self, request):

        self._logger.debug(f"request: {request}")
        for uuid, message in request.items():
            self._logger.debug(f"message: {message}")
            content = message[MESSAGE_CONTENT]
            # TODO A lot of information needs to be known here
            html_content = content[MESSAGE_HTML]
            header_content = self._preprocess_header(content[MESSAGE_HEADERS])

            starting_extraction = get_utc_now()
            meta_data = self._extract_meta_data(html_content, header_content)
            meta_data.update({"time_for_extraction": get_utc_now() - starting_extraction})

            response = meta_data
            self.manager_to_api_queue.put({uuid: response})


def api_server(queue, return_queue):
    app.api_queue = ProcessToDaemonCommunication(queue, return_queue)
    uvicorn.run(app, host="0.0.0.0", port=API_PORT, log_level="info")


if __name__ == '__main__':
    manager = Manager()