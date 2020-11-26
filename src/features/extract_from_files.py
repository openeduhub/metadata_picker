import base64
import os
import zipfile
from urllib.parse import urlparse

import PyPDF2
import requests
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text

from features.metadata_base import MetadataBase
from features.website_manager import WebsiteData
from lib.constants import VALUES
from lib.settings import RETURN_IMAGES_IN_METADATA


class ExtractFromFiles(MetadataBase):
    def _download_file(self, file_url, filename):
        result = requests.get(file_url)
        if result.status_code != 200:
            self._logger.warning(
                f"Downloading tag list from '{file_url}' yielded status code '{result.status_code}'."
            )

        open(filename, "wb").write(result.content)

    @staticmethod
    def _extract_docx(filename) -> dict:
        document = zipfile.ZipFile(filename)

        xml_files = document.filelist

        extracted_content = []
        images = {}

        for xml_file in xml_files:
            if xml_file.filename.find(".xml") >= 0:
                content = document.read(xml_file, pwd=None).decode()
                soup = BeautifulSoup(content, "xml")

                body = None
                if xml_file.filename == "word/document.xml":
                    body = soup.document.body
                elif xml_file.filename == "word/footer1.xml":
                    body = soup.ftr
                elif xml_file.filename == "word/header1.xml":
                    body = soup.hdr

                text_pieces = []
                if body:
                    text_pieces = [tag.string for tag in body.find_all("t")]

                extracted_content += text_pieces
            elif (
                RETURN_IMAGES_IN_METADATA
                and xml_file.filename.find("media") >= 0
            ):
                image = document.read(xml_file, pwd=None)
                image = base64.b64encode(image).decode()

                images.update({xml_file.filename: image})

        content = {"extracted_content": extracted_content, "images": images}

        return content

    @staticmethod
    def _extract_pdfs(filename) -> dict:
        extracted_content = []
        pdf_file = PyPDF2.PdfFileReader(open(filename, "rb"))

        extracted_content += f"{pdf_file.getDocumentInfo()}"

        data = pdf_file.getXmpMetadata()

        xmp_metadata = [
            "dc_contributor",
            "dc_coverage",
            "dc_creator",
            "dc_date",
            "dc_description",
            "dc_format",
            "dc_identifier",
            "dc_language",
            "dc_publisher",
            "dc_relation",
            "dc_rights",
            "dc_source",
            "dc_subject",
            "dc_title",
            "dc_type",
            "pdf_keywords",
            "pdf_pdfversion",
            "pdf_producer",
            "xmp_createDate",
            "xmp_modifyDate",
            "xmp_metadataDate",
            "xmp_creatorTool",
            "xmpmm_documentId",
            "xmpmm_instanceId",
        ]
        for parameter in xmp_metadata:
            extracted_content += f"{parameter}, {getattr(data, parameter)}"

        extracted_content += extract_text(filename)

        images = []
        for page in range(pdf_file.getNumPages()):
            pdf_page = pdf_file.getPage(page)
            x_object = pdf_page["/Resources"]["/XObject"].getObject()

            for obj in x_object:
                if x_object[obj]["/Subtype"] == "/Image":
                    images += obj

        content = {"extracted_content": extracted_content, "images": images}
        return content

    def _work_files(self, files):
        values = {VALUES: []}

        for file in files:
            filename = os.path.basename(urlparse(file).path)
            extension = filename.split(".")[-1]
            self._download_file(file, filename)

            content = {"extracted_content": [], "images": {}}
            if extension == "docx":
                content = self._extract_docx(filename)
            elif extension == "pdf":
                content = self._extract_pdfs(filename)

            if len(content["extracted_content"]) > 0:
                values[VALUES].append(filename)

            os.remove(filename)

        return values

    @staticmethod
    def _get_extractable_files(website_data: WebsiteData):
        file_extensions = [
            os.path.splitext(link)[-1] for link in website_data.raw_links
        ]

        extractable_files = [
            file
            for file, extension in zip(website_data.raw_links, file_extensions)
            if extension in [".docx", ".pdf"]
        ]

        return extractable_files

    def _start(self, website_data: WebsiteData) -> dict:
        extractable_files = self._get_extractable_files(website_data)

        values = self._work_files(files=extractable_files)
        return {**values}

    def _calculate_probability(self, website_data: WebsiteData) -> float:
        probability = 0
        extractable_files = self._get_extractable_files(website_data)

        if len(website_data.values) > 0:
            probability = len(extractable_files) / len(website_data.values)

        return probability