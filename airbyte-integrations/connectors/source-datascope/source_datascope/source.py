# MIT License
#
# Copyright (c) 2020 Airbyte
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


from abc import ABC
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple
from datetime import datetime, timedelta
import logging
import backoff
import time
from airbyte_cdk.logger import AirbyteLogger

import requests
from requests.exceptions import ConnectionError
from requests.structures import CaseInsensitiveDict
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream
from airbyte_cdk.sources.streams.http.auth import TokenAuthenticator
from airbyte_cdk.sources.streams.http.auth import NoAuth



# Basic full refresh stream
class DatascopeStream(HttpStream, ABC):

    # TODO: Fill in the url base. Required.
    url_base = "http://54.71.5.215/api/external/v3/"

    queries_per_hour = 1000

    def __init__(self, token: str, form_id: str, start_date: str, **kwargs):
        super().__init__()
        self.token = token
        self.form_id = form_id
        self.start_date = start_date
        self.BASE_URL = "https://mydatascope.com"
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


    @backoff.on_exception(backoff.expo, requests.exceptions.ConnectionError, max_tries=7)
    def _request(self, url: str, method: str = "GET", data: dict = None) -> List[dict]:
        response = requests.request(method, url, headers=self._headers, json=data)

        if response.status_code == 200:
            response_data = response.json()
            if isinstance(response_data, list):
                return response_data
            else:
                return [response_data]

    @property
    def cursor_field(self) -> str:
        return "updated_at_unix"
    

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        decoded_response = response.json()
        if decoded_response:
            #offset by created form_answer_id
            last_object_date = decoded_response[-1]["updated_at_unix"]
            if last_object_date:
                return {"offset": last_object_date}
            else:
                return None
        else:
            return None

    def request_params(self, next_page_token: Mapping[str, Any] = None, **kwargs) -> MutableMapping[str, Any]:
        # The api requires that we include the base currency as a query param so we do that in this method
        params = { 'form_id': self.form_id, 'token': self.token, 'start': self.start_date}
        if next_page_token:
            params.update(**next_page_token)
        return params

    def parse_response(self, response: requests.Response, stream_state: Mapping[str, Any], **kwargs) -> Iterable[Mapping]:
        time.sleep(3600 / self.queries_per_hour)
        return response.json()


class DatascopeIncrementalStream(DatascopeStream, ABC):

    def filter_by_state(self, stream_state: Mapping[str, Any] = None, record: Mapping[str, Any] = None) -> Iterable:
        record_date = record.get(self.cursor_field)
        stream_date = self.start_date
        if stream_state.get(self.cursor_field):
            stream_date = stream_state.get(self.cursor_field)
            stream_state = int(stream_date)
            record_date = int(record_date)
        #AirbyteLogger().log("INFO", f"record date: {record_date}")
        #AirbyteLogger().log("INFO", f"stream date: {stream_date}")
        if not stream_date or record_date > stream_date:
            yield record

    def get_updated_state(self, current_stream_state: MutableMapping[str, Any], latest_record: Mapping[str, Any]) -> Mapping[str, any]:
        current_stream_state = current_stream_state or {}
        latest_record_date = self.start_date
        start_date = self.start_date
        if latest_record:
            latest_record_date = latest_record[self.cursor_field]
        current_stream_state_date = current_stream_state.get(self.cursor_field, self.start_date)
        cursor_state = max(current_stream_state_date, latest_record_date)
        return {self.cursor_field: cursor_state }

    def request_params(self, next_page_token: Mapping[str, Any] = None, stream_state: Mapping[str, Any] = None, **kwargs) -> MutableMapping[str, Any]:
        # The api requires that we include the base currency as a query param so we do that in this method
        stream_state = stream_state or {}
        start_date = self.start_date
        last_date = stream_state.get(self.cursor_field, start_date)
        params = { 'form_id': self.form_id, 'token': self.token}
        params['date_modified'] = True
        if next_page_token:
            params.update(**next_page_token)
        else:
            params.update(**{'offset': last_date})

        #AirbyteLogger().log("INFO", f"schema type: {self.schema_type}")
        AirbyteLogger().log("INFO", f"params request: {params}")
        #AirbyteLogger().log("INFO", f"cursor: {self.cursor_field}")
        return params



class Forms(DatascopeIncrementalStream):
    primary_key = "form_answer_id"

    def path(self, **kwargs) -> str:
        return "answers_static"

    def get_json_schema(self):
        schema = super().get_json_schema()
        return schema

class Forms(DatascopeIncrementalStream):
    primary_key = "form_answer_id"

    def path(self, **kwargs) -> str:
        return "answers_static"

    def get_json_schema(self):
        schema = super().get_json_schema()
        return schema


# Source
class SourceDatascope(AbstractSource):
    def check_connection(self, logger, config) -> Tuple[bool, any]:
        return True, None

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        auth = TokenAuthenticator(config['api_key'])
        start_date = datetime.strptime(config['start_date'], '%Y-%m-%dT%H:%M:%S%z')
        start_date = time.mktime(start_date.timetuple())
        AirbyteLogger().log("INFO", f"start date: {config['start_date']}")
        return [Forms(authenticator=auth, token=config['api_key'], form_id=config['form_id'], start_date=start_date)]
