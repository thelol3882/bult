import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ReplicaState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    REPLICA_STATE_UNSPECIFIED: _ClassVar[ReplicaState]
    REPLICA_STATE_RUNNING: _ClassVar[ReplicaState]
    REPLICA_STATE_EXITED: _ClassVar[ReplicaState]
REPLICA_STATE_UNSPECIFIED: ReplicaState
REPLICA_STATE_RUNNING: ReplicaState
REPLICA_STATE_EXITED: ReplicaState

class RunReplicaRequest(_message.Message):
    __slots__ = ("replica_id", "image", "container_port", "limits", "env")
    REPLICA_ID_FIELD_NUMBER: _ClassVar[int]
    IMAGE_FIELD_NUMBER: _ClassVar[int]
    CONTAINER_PORT_FIELD_NUMBER: _ClassVar[int]
    LIMITS_FIELD_NUMBER: _ClassVar[int]
    ENV_FIELD_NUMBER: _ClassVar[int]
    replica_id: str
    image: ImageRef
    container_port: int
    limits: Limits
    env: _containers.RepeatedCompositeFieldContainer[EnvVar]
    def __init__(self, replica_id: _Optional[str] = ..., image: _Optional[_Union[ImageRef, _Mapping]] = ..., container_port: _Optional[int] = ..., limits: _Optional[_Union[Limits, _Mapping]] = ..., env: _Optional[_Iterable[_Union[EnvVar, _Mapping]]] = ...) -> None: ...

class RunReplicaResponse(_message.Message):
    __slots__ = ("replica",)
    REPLICA_FIELD_NUMBER: _ClassVar[int]
    replica: Replica
    def __init__(self, replica: _Optional[_Union[Replica, _Mapping]] = ...) -> None: ...

class EnvVar(_message.Message):
    __slots__ = ("name", "value")
    NAME_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    name: str
    value: str
    def __init__(self, name: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

class Limits(_message.Message):
    __slots__ = ("cpu_millicores", "memory_bytes")
    CPU_MILLICORES_FIELD_NUMBER: _ClassVar[int]
    MEMORY_BYTES_FIELD_NUMBER: _ClassVar[int]
    cpu_millicores: int
    memory_bytes: int
    def __init__(self, cpu_millicores: _Optional[int] = ..., memory_bytes: _Optional[int] = ...) -> None: ...

class ImageRef(_message.Message):
    __slots__ = ("repository", "digest")
    REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    DIGEST_FIELD_NUMBER: _ClassVar[int]
    repository: str
    digest: str
    def __init__(self, repository: _Optional[str] = ..., digest: _Optional[str] = ...) -> None: ...

class Replica(_message.Message):
    __slots__ = ("replica_id", "state", "host_port", "image", "started_at", "exit_code")
    REPLICA_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    HOST_PORT_FIELD_NUMBER: _ClassVar[int]
    IMAGE_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    EXIT_CODE_FIELD_NUMBER: _ClassVar[int]
    replica_id: str
    state: ReplicaState
    host_port: int
    image: ImageRef
    started_at: _timestamp_pb2.Timestamp
    exit_code: int
    def __init__(self, replica_id: _Optional[str] = ..., state: _Optional[_Union[ReplicaState, str]] = ..., host_port: _Optional[int] = ..., image: _Optional[_Union[ImageRef, _Mapping]] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., exit_code: _Optional[int] = ...) -> None: ...

class StopReplicaRequest(_message.Message):
    __slots__ = ("replica_id",)
    REPLICA_ID_FIELD_NUMBER: _ClassVar[int]
    replica_id: str
    def __init__(self, replica_id: _Optional[str] = ...) -> None: ...

class StopReplicaResponse(_message.Message):
    __slots__ = ("replica",)
    REPLICA_FIELD_NUMBER: _ClassVar[int]
    replica: Replica
    def __init__(self, replica: _Optional[_Union[Replica, _Mapping]] = ...) -> None: ...

class StartReplicaRequest(_message.Message):
    __slots__ = ("replica_id",)
    REPLICA_ID_FIELD_NUMBER: _ClassVar[int]
    replica_id: str
    def __init__(self, replica_id: _Optional[str] = ...) -> None: ...

class StartReplicaResponse(_message.Message):
    __slots__ = ("replica",)
    REPLICA_FIELD_NUMBER: _ClassVar[int]
    replica: Replica
    def __init__(self, replica: _Optional[_Union[Replica, _Mapping]] = ...) -> None: ...

class RemoveReplicaRequest(_message.Message):
    __slots__ = ("replica_id",)
    REPLICA_ID_FIELD_NUMBER: _ClassVar[int]
    replica_id: str
    def __init__(self, replica_id: _Optional[str] = ...) -> None: ...

class RemoveReplicaResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListReplicasRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListReplicasResponse(_message.Message):
    __slots__ = ("replicas",)
    REPLICAS_FIELD_NUMBER: _ClassVar[int]
    replicas: _containers.RepeatedCompositeFieldContainer[Replica]
    def __init__(self, replicas: _Optional[_Iterable[_Union[Replica, _Mapping]]] = ...) -> None: ...

class LogsRequest(_message.Message):
    __slots__ = ("replica_id", "follow", "tail_lines")
    REPLICA_ID_FIELD_NUMBER: _ClassVar[int]
    FOLLOW_FIELD_NUMBER: _ClassVar[int]
    TAIL_LINES_FIELD_NUMBER: _ClassVar[int]
    replica_id: str
    follow: bool
    tail_lines: int
    def __init__(self, replica_id: _Optional[str] = ..., follow: _Optional[bool] = ..., tail_lines: _Optional[int] = ...) -> None: ...

class LogsResponse(_message.Message):
    __slots__ = ("data",)
    DATA_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    def __init__(self, data: _Optional[bytes] = ...) -> None: ...
