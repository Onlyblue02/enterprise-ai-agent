import json
import os
from pathlib import Path
from typing import Sequence

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict

import config_data as config


def get_history(session_id):
    return FileChatMessageHistory(session_id, config.chat_history_directory)

class FileChatMessageHistory(BaseChatMessageHistory):

    def __init__(self,session_id,storage_path):
        self.session_id=session_id
        self.storage_path = Path(storage_path)
        # 完整的文件路径
        self.file_path = self.storage_path / f"{self.session_id}.json"
        # 确保文件夹存在
        self.storage_path.mkdir(parents=True, exist_ok=True)
    def add_messages(self, messages: Sequence[BaseMessage])->None:
        # Sequence序列 类似list \ tuple
        all_messages=list(self.messages) # 已有的消息列表
        all_messages.extend(messages)    # 新的和已有的融合成一个list
        #
        # new_messages=[]
        # for message in all_messages:
        #     d=message_to_dirt(message)
        #     new_messages.append(d)d
        new_messages=[message_to_dict(message) for message in all_messages]
        # 将数据写入文件
        temp_path = self.file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(new_messages, file, ensure_ascii=False)
        os.replace(temp_path, self.file_path)
    @property     #装饰器将message方法编程成员属性用
    def messages(self)-> list[BaseMessage]:
        # 当前文件内： list[字典]
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                message_data = json.load(file)
                return messages_from_dict(message_data)
        except (FileNotFoundError,json.JSONDecodeError):        # 只捕获filenotfound，但未处理JSONDecodeError等其他异常

            """当以历史纪录文件存在但内容为空，或损坏时，例如手动清空文件或写入不完整，JSON.load(F)会抛出JSONDecoderERROR，导致系统崩溃"""

            return []

    def clear(self) -> None:
        with open(self.file_path, "w", encoding="utf-8") as file:
            json.dump([], file)

