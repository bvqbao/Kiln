from __future__ import annotations

import json
from enum import Enum, IntEnum
from typing import TYPE_CHECKING, Dict, List, Literal, Self, Union

import jsonschema
import jsonschema.exceptions
from kiln_ai.datamodel.json_schema import JsonObjectSchema, schema_from_json_str
from pydantic import BaseModel, Field, model_validator

from .basemodel import ID_TYPE, KilnBaseModel, KilnParentedModel, KilnParentModel
from .json_schema import validate_schema

if TYPE_CHECKING:
    from . import Task

# Conventions:
# 1) Names are filename safe as they may be used as file names. They are informational and not to be used in prompts/training/validation.
# 2) Descrptions are for Kiln users to describe/understanding the purpose of this object. They must never be used in prompts/training/validation. Use "instruction/requirements" instead.

# Filename compatible names
NAME_REGEX = r"^[A-Za-z0-9 _-]+$"
NAME_FIELD = Field(min_length=1, max_length=120, pattern=NAME_REGEX)


class Priority(IntEnum):
    p0 = 0
    p1 = 1
    p2 = 2
    p3 = 3


# Only one rating type for now, but this allows for extensibility if we want to add more in the future
class TaskOutputRatingType(str, Enum):
    five_star = "five_star"
    custom = "custom"


class TaskOutputRating(KilnBaseModel):
    """
    A rating for a task output, including an overall rating and ratings for each requirement.

    Only supports five star ratings for now, but extensible for custom values.
    """

    type: TaskOutputRatingType = Field(default=TaskOutputRatingType.five_star)
    rating: float = Field(description="The rating value (typically 1-5 stars).")
    requirement_ratings: Dict[ID_TYPE, float] = Field(
        default={},
        description="The ratings of the requirements of the task. The keys are the ids of the requirements. The values are the ratings (typically 1-5 stars).",
    )

    @model_validator(mode="after")
    def validate_rating(self) -> Self:
        if self.type not in TaskOutputRatingType:
            raise ValueError(f"Invalid rating type: {self.type}")

        if self.type == TaskOutputRatingType.five_star:
            self._validate_five_star(self.rating, "overall rating")
            for req_id, req_rating in self.requirement_ratings.items():
                self._validate_five_star(req_rating, f"requirement rating for {req_id}")

        return self

    def _validate_five_star(self, rating: float, rating_name: str) -> None:
        if not isinstance(rating, float) or not rating.is_integer():
            raise ValueError(
                f"{rating_name.capitalize()} of type five_star must be an integer value (1.0, 2.0, 3.0, 4.0, or 5.0)"
            )
        if rating < 1 or rating > 5:
            raise ValueError(
                f"{rating_name.capitalize()} of type five_star must be between 1 and 5 stars"
            )


class TaskOutput(KilnParentedModel):
    """
    An output from a specific task input.
    """

    output: str = Field(
        description="The output of the task. JSON formatted for structured output, plaintext for unstructured output."
    )
    source: DataSourceType = Field(
        description="The source of the output: human or synthetic."
    )
    # TODO: add structure/validation to this. For human creator_id. Model ID and verion and provider for models
    source_properties: Dict[str, str] = Field(
        default={},
        description="Additional properties of the source, e.g. the user name of the human who provided the output or the model that generated the output.",
    )
    rating: TaskOutputRating | None = Field(
        default=None, description="The rating of the output"
    )

    fixed_output: str | None = Field(
        default=None,
        description="An version of the output with issues fixed by a human evaluator. This must be a 'fixed' version of the existing output, and not an entirely new output. If you wish to generate an ideal curatorial output for this task unrelated to this output, generate a new TaskOutput with type 'human' instead of using this field.",
    )

    def parent_task_run(self) -> TaskRun | None:
        if not isinstance(self.parent, TaskRun):
            return None
        return self.parent

    # TODO validators for output and fixed_output: validate they follow the tas

    @model_validator(mode="after")
    def validate_output_format(self) -> Self:
        task = self.task_for_validation()
        if task is None:
            # don't validate this relationship until we have a path or parent. Give them time to build it (but will catch it before saving)
            return self

        # validate output
        if task.output_json_schema is not None:
            try:
                validate_schema(json.loads(self.output), task.output_json_schema)
            except json.JSONDecodeError:
                raise ValueError("Output is not a valid JSON object")
            except jsonschema.exceptions.ValidationError as e:
                raise ValueError(f"Output does not match task output schema: {e}")
        return self

    def task_for_validation(self) -> Task | None:
        task_output = self.parent_task_run()
        if task_output is None:
            return None
        if not isinstance(task_output, TaskRun):
            raise ValueError("TaskOutput must have a valid parent TaskRun")

        task = task_output.parent
        if task is None:
            return None
        if not isinstance(task, Task):
            raise ValueError(
                "TaskOutput's parent TaskRun must have a valid parent Task"
            )
        return task

    @model_validator(mode="after")
    def validate_requirement_rating_keys(self) -> Self:
        if self.rating is None or len(self.rating.requirement_ratings) == 0:
            return self
        task = self.task_for_validation()
        if task is None:
            # don't validate this relationship until we have a path or parent. Give them time to build it (but will catch it before saving)
            return self

        valid_requirement_ids = {req.id for req in task.requirements()}
        for key in self.rating.requirement_ratings.keys():
            if key not in valid_requirement_ids:
                raise ValueError(
                    f"Requirement ID '{key}' is not a valid requirement ID for this task"
                )
        return self

    @model_validator(mode="after")
    def validate_source_properties(self) -> Self:
        if self.source == DataSourceType.synthetic:
            required_keys = {
                "adapter_name",
                "model_name",
                "model_provider",
                "prompt_builder_name",
            }
        elif self.source == DataSourceType.human:
            required_keys = {"creator"}
        else:
            raise ValueError(f"Invalid source type: {self.source}")

        missing_keys = []
        for key in required_keys:
            if key not in self.source_properties:
                missing_keys.append(key)
            elif self.source_properties[key] == "":
                raise ValueError(
                    f"TaskOutput source_properties[{key}] must not be empty string for {self.source} outputs"
                )
        if len(missing_keys) > 0:
            raise ValueError(
                f"TaskOutput source_properties must include {missing_keys} for {self.source} outputs"
            )
        return self


class DataSourceType(str, Enum):
    """
    The source of a piece of data.
    """

    human = "human"
    synthetic = "synthetic"


class DataSourceProperty(BaseModel):
    name: str
    type: Union[Literal["str"], Literal["int"], Literal["float"]]
    required_for: List[DataSourceType] = []
    not_allowed_for: List[DataSourceType] = []


class DataSource(BaseModel):
    type: DataSourceType
    properties: Dict[str, str | int | float] = Field(
        default={},
        description="Properties describing the data source. For synthetic things like model. For human, the human's name.",
    )

    _data_source_properties = [
        DataSourceProperty(
            name="created_by",
            type="str",
            required_for=[DataSourceType.human],
            not_allowed_for=[DataSourceType.synthetic],
        ),
        DataSourceProperty(
            name="model_name",
            type="str",
            required_for=[DataSourceType.synthetic],
            not_allowed_for=[DataSourceType.human],
        ),
        DataSourceProperty(
            name="model_provider",
            type="str",
            required_for=[DataSourceType.synthetic],
            not_allowed_for=[DataSourceType.human],
        ),
        DataSourceProperty(
            name="prompt_type",
            type="str",
            not_allowed_for=[DataSourceType.human],
        ),
    ]

    @model_validator(mode="after")
    def validate_properties(self) -> "DataSource":
        for prop in self._data_source_properties:
            if self.type in prop.required_for:
                if prop.name not in self.properties:
                    raise ValueError(
                        f"'{prop.name}' is required for {self.type} data source"
                    )
                if not isinstance(self.properties[prop.name], eval(prop.type)):
                    raise ValueError(
                        f"'{prop.name}' must be of type {prop.type} for {self.type} data source"
                    )
            elif self.type in prop.not_allowed_for and prop.name in self.properties:
                raise ValueError(
                    f"'{prop.name}' is not allowed for {self.type} data source"
                )
        return self


class TaskRun(KilnParentedModel, KilnParentModel, parent_of={"outputs": TaskOutput}):
    """
    An run of a specific Task, including the input and output.
    """

    input: str = Field(
        description="The inputs to the task. JSON formatted for structured input, plaintext for unstructured input."
    )
    source: DataSourceType = Field(
        description="The source of the input: human or synthetic."
    )
    # TODO add structure/validation to this. For human creator_id. Model: synthetic data tool and model version
    source_properties: Dict[str, str] = Field(
        default={},
        description="Additional properties of the source, e.g. the name of the human who provided the input or the model that generated the input.",
    )

    # Needed for typechecking. TODO P2: fix this in KilnParentModel
    def outputs(self) -> list[TaskOutput]:
        return super().outputs()  # type: ignore

    def parent_task(self) -> Task | None:
        if not isinstance(self.parent, Task):
            return None
        return self.parent

    @model_validator(mode="after")
    def validate_input_format(self) -> Self:
        task = self.parent
        if task is None:
            # don't validate this relationship until we have a path or parent. Give them time to build it (but will catch it before saving)
            return self
        if not isinstance(task, Task):
            raise ValueError(
                "TaskOutput's parent TaskRun must have a valid parent Task"
            )

        # validate output
        if task.input_json_schema is not None:
            try:
                validate_schema(json.loads(self.input), task.input_json_schema)
            except json.JSONDecodeError:
                raise ValueError("Input is not a valid JSON object")
            except jsonschema.exceptions.ValidationError as e:
                raise ValueError(f"Input does not match task input schema: {e}")
        return self


class TaskRequirement(KilnParentedModel):
    name: str = NAME_FIELD
    description: str = Field(default="")
    instruction: str = Field(min_length=1)
    priority: Priority = Field(default=Priority.p2)


class TaskDeterminism(str, Enum):
    deterministic = "deterministic"  # Expect exact match
    semantic_match = "semantic_match"  # Expect same meaning, but flexible on expression of the meaning
    flexible = "flexible"  # Flexible on semantic output. Eval should be custom based on parsing requirements.


class Task(
    KilnParentedModel,
    KilnParentModel,
    parent_of={"requirements": TaskRequirement, "runs": TaskRun},
):
    name: str = NAME_FIELD
    description: str = Field(default="")
    priority: Priority = Field(default=Priority.p2)
    determinism: TaskDeterminism = Field(default=TaskDeterminism.flexible)
    instruction: str = Field(min_length=1)
    # TODO: make this required, or formalize the default message output schema
    output_json_schema: JsonObjectSchema | None = None
    input_json_schema: JsonObjectSchema | None = None

    def output_schema(self) -> Dict | None:
        if self.output_json_schema is None:
            return None
        return schema_from_json_str(self.output_json_schema)

    def input_schema(self) -> Dict | None:
        if self.input_json_schema is None:
            return None
        return schema_from_json_str(self.input_json_schema)

    # Needed for typechecking. TODO P2: fix this in KilnParentModel
    def requirements(self) -> list[TaskRequirement]:
        return super().requirements()  # type: ignore

    # Needed for typechecking. TODO P2: fix this in KilnParentModel
    def runs(self) -> list[TaskRun]:
        return super().runs()  # type: ignore


class Project(KilnParentModel, parent_of={"tasks": Task}):
    name: str = NAME_FIELD
    description: str = Field(default="")

    # Needed for typechecking. TODO P2: fix this in KilnParentModel
    def tasks(self) -> list[Task]:
        return super().tasks()  # type: ignore
