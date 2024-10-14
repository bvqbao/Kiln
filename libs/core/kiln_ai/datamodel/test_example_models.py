import json

import pytest
from kiln_ai.datamodel import (
    DataSourceType,
    Project,
    Task,
    TaskDeterminism,
    TaskOutput,
    TaskOutputRating,
    TaskRequirement,
    TaskRun,
)
from pydantic import ValidationError


def test_task_model_validation(tmp_path):
    # Valid task
    task = Task(
        name="Test Task",
        instruction="test instruction",
        path=tmp_path / Task.base_filename(),
    )
    task.save_to_file()
    task_output = TaskRun(
        parent=task,
        input="Test input",
        source=DataSourceType.human,
        source_properties={"creator": "John Doe"},
    )
    assert task_output.input == "Test input"
    assert task_output.source == DataSourceType.human
    assert task_output.source_properties == {"creator": "John Doe"}

    # Invalid source
    with pytest.raises(ValidationError):
        TaskRun(
            parent=task,
            input="Test input",
            source="invalid_source",
            source_properties={},
        )

    # Missing required field
    with pytest.raises(ValidationError):
        TaskRun(parent=task, source=DataSourceType.human, source_properties={})

    # Invalid source_properties type
    with pytest.raises(ValidationError):
        TaskRun(
            parent=task,
            input="Test input",
            source=DataSourceType.human,
            source_properties="invalid",
        )


def test_task_output_relationship(tmp_path):
    task = Task(
        name="Test Task",
        instruction="test instruction",
        path=tmp_path / Task.base_filename(),
    )
    task.save_to_file()
    task_output = TaskRun(
        parent=task,
        input="Test input",
        source=DataSourceType.human,
        source_properties={},
    )
    assert task_output.__class__.relationship_name() == "runs"
    assert task_output.__class__.parent_type().__name__ == "Task"


def test_task_output_model_validation(tmp_path):
    # Valid task output
    task = Task(
        name="Test Task",
        instruction="test instruction",
        path=tmp_path / Task.base_filename(),
    )
    task.save_to_file()
    task_output = TaskRun(input="Test input", source=DataSourceType.human, parent=task)
    task_output.save_to_file()
    valid_output = TaskOutput(
        parent=task_output,
        output="Test output",
        source=DataSourceType.human,
        source_properties={"creator": "Jane Doe"},
    )
    assert valid_output.output == "Test output"
    assert valid_output.source == DataSourceType.human
    assert valid_output.source_properties == {"creator": "Jane Doe"}

    # Invalid source
    with pytest.raises(ValidationError):
        TaskOutput(
            path="/test/path",
            output="Test output",
            source="invalid_source",
            source_properties={},
        )

    # Missing required field
    with pytest.raises(ValidationError):
        TaskOutput(
            path="/test/path",
            source=DataSourceType.human,
            source_properties={},
        )


def test_structured_output_workflow(tmp_path):
    tmp_project_file = (
        tmp_path / "test_structured_output_runs" / Project.base_filename()
    )
    # Create project
    project = Project(name="Test Project", path=str(tmp_project_file))
    project.save_to_file()

    # Create task with requirements
    task = Task(
        name="Structured Output Task",
        parent=project,
        instruction="Generate a JSON object with name and age",
        determinism=TaskDeterminism.semantic_match,
        output_json_schema=json.dumps(
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                "required": ["name", "age"],
            }
        ),
    )
    task.save_to_file()

    req1 = TaskRequirement(
        name="Req1", instruction="Name must be capitalized", parent=task
    )
    req2 = TaskRequirement(name="Req2", instruction="Age must be positive", parent=task)
    req1.save_to_file()
    req2.save_to_file()

    # Create runs
    runs = []
    for source in DataSourceType:
        for _ in range(2):
            task_output = TaskRun(
                input="Generate info for John Doe",
                source=source,
                parent=task,
            )
            task_output.save_to_file()
            runs.append(task_output)

    # Create outputs
    outputs = []
    for task_output in runs:
        output = TaskOutput(
            output='{"name": "John Doe", "age": 30}',
            source=DataSourceType.human,
            source_properties={"creator": "john_doe"},
            parent=task_output,
        )
        output.save_to_file()
        outputs.append(output)

    # Update outputs with ratings
    for output in outputs:
        output.rating = TaskOutputRating(
            rating=4,
            requirement_ratings={
                req1.id: 5,
                req2.id: 5,
            },
        )
        output.save_to_file()

    # Update outputs with fixed_output
    outputs[0].fixed_output = '{"name": "John Doe", "age": 31}'
    outputs[0].save_to_file()

    # Load from disk and validate
    loaded_project = Project.load_from_file(tmp_project_file)
    loaded_task = loaded_project.tasks()[0]

    assert loaded_task.name == "Structured Output Task"
    assert len(loaded_task.requirements()) == 2
    assert len(loaded_task.runs()) == 4

    loaded_runs = loaded_task.runs()
    for task_output in loaded_runs:
        outputs = task_output.outputs()
        assert len(outputs) == 1
        output = outputs[0]
        assert output.rating is not None
        assert len(output.rating.requirement_ratings) == 2

    # Find the run with the fixed output
    run_with_fixed_output = next(
        (
            task_output
            for task_output in loaded_runs
            if task_output.outputs()[0].fixed_output is not None
        ),
        None,
    )
    assert run_with_fixed_output is not None, "No run found with fixed output"
    assert (
        run_with_fixed_output.outputs()[0].fixed_output
        == '{"name": "John Doe", "age": 31}'
    )


def test_task_output_requirement_rating_keys(tmp_path):
    # Create a project, task, and example hierarchy
    project = Project(name="Test Project", path=(tmp_path / "test_project"))
    project.save_to_file()
    task = Task(name="Test Task", parent=project, instruction="Task instruction")
    task.save_to_file()
    task_output = TaskRun(input="Test input", source=DataSourceType.human, parent=task)
    task_output.save_to_file()

    # Create task requirements
    req1 = TaskRequirement(
        name="Requirement 1", parent=task, instruction="Requirement 1 instruction"
    )
    req1.save_to_file()
    req2 = TaskRequirement(
        name="Requirement 2", parent=task, instruction="Requirement 2 instruction"
    )
    req2.save_to_file()
    # Valid case: all requirement IDs are valid
    valid_output = TaskOutput(
        output="Test output",
        source=DataSourceType.human,
        source_properties={"creator": "john_doe"},
        parent=task_output,
        rating=TaskOutputRating(
            rating=4,
            requirement_ratings={
                req1.id: 5,
                req2.id: 4,
            },
        ),
    )
    valid_output.save_to_file()
    assert valid_output.rating.requirement_ratings is not None

    # Invalid case: unknown requirement ID
    with pytest.raises(
        ValueError,
        match="Requirement ID .* is not a valid requirement ID for this task",
    ):
        output = TaskOutput(
            output="Test output",
            source=DataSourceType.human,
            source_properties={"creator": "john_doe"},
            parent=task_output,
            rating=TaskOutputRating(
                rating=4,
                requirement_ratings={
                    "unknown_id": 5,
                },
            ),
        )
        output.save_to_file()


def test_task_output_schema_validation(tmp_path):
    # Create a project, task, and example hierarchy
    project = Project(name="Test Project", path=(tmp_path / "test_project"))
    project.save_to_file()
    task = Task(
        name="Test Task",
        instruction="test instruction",
        parent=project,
        output_json_schema=json.dumps(
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                "required": ["name", "age"],
            }
        ),
    )
    task.save_to_file()
    task_output = TaskRun(
        input="Test input",
        source=DataSourceType.human,
        parent=task,
        source_properties={"creator": "john_doe"},
    )
    task_output.save_to_file()

    # Create an example output with a valid schema
    valid_output = TaskOutput(
        output='{"name": "John Doe", "age": 30}',
        source=DataSourceType.human,
        source_properties={"creator": "john_doe"},
        parent=task_output,
    )
    valid_output.save_to_file()

    # changing to invalid output
    with pytest.raises(ValueError):
        valid_output.output = '{"name": "John Doe", "age": "thirty"}'
        valid_output.save_to_file()

    # Invalid case: output does not match task output schema
    with pytest.raises(ValueError):
        output = TaskOutput(
            output='{"name": "John Doe", "age": "thirty"}',
            source=DataSourceType.human,
            source_properties={"creator": "john_doe"},
            parent=task_output,
        )
        output.save_to_file()


def test_task_output_schema_validation(tmp_path):
    # Create a project and task hierarchy
    project = Project(name="Test Project", path=(tmp_path / "test_project"))
    project.save_to_file()
    task = Task(
        name="Test Task",
        parent=project,
        instruction="test instruction",
        input_json_schema=json.dumps(
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                "required": ["name", "age"],
            }
        ),
    )
    task.save_to_file()

    # Create an example with a valid input schema
    valid_task_output = TaskRun(
        input='{"name": "John Doe", "age": 30}',
        source=DataSourceType.human,
        parent=task,
    )
    valid_task_output.save_to_file()

    # Changing to invalid input
    with pytest.raises(ValueError):
        valid_task_output.input = '{"name": "John Doe", "age": "thirty"}'
        valid_task_output.save_to_file()

    # Invalid case: input does not match task input schema
    with pytest.raises(ValueError):
        task_output = TaskRun(
            input='{"name": "John Doe", "age": "thirty"}',
            source=DataSourceType.human,
            parent=task,
        )
        task_output.save_to_file()


def test_valid_human_task_output():
    output = TaskOutput(
        output="Test output",
        source=DataSourceType.human,
        source_properties={"creator": "John Doe"},
    )
    assert output.source == DataSourceType.human
    assert output.source_properties["creator"] == "John Doe"


def test_invalid_human_task_output_missing_creator():
    with pytest.raises(
        ValidationError,
        match="must include \['creator'\]",
    ):
        TaskOutput(
            output="Test output", source=DataSourceType.human, source_properties={}
        )


def test_invalid_human_task_output_empty_creator():
    with pytest.raises(ValidationError, match="must not be empty string"):
        TaskOutput(
            output="Test output",
            source=DataSourceType.human,
            source_properties={"creator": ""},
        )


def test_valid_synthetic_task_output():
    output = TaskOutput(
        output="Test output",
        source=DataSourceType.synthetic,
        source_properties={
            "adapter_name": "TestAdapter",
            "model_name": "GPT-4",
            "model_provider": "OpenAI",
            "prompt_builder_name": "TestPromptBuilder",
        },
    )
    assert output.source == DataSourceType.synthetic
    assert output.source_properties["adapter_name"] == "TestAdapter"
    assert output.source_properties["model_name"] == "GPT-4"
    assert output.source_properties["model_provider"] == "OpenAI"
    assert output.source_properties["prompt_builder_name"] == "TestPromptBuilder"


def test_invalid_synthetic_task_output_missing_keys():
    with pytest.raises(
        ValidationError, match="TaskOutput source_properties must include"
    ):
        TaskOutput(
            output="Test output",
            source=DataSourceType.synthetic,
            source_properties={"adapter_name": "TestAdapter", "model_name": "GPT-4"},
        )


def test_invalid_synthetic_task_output_empty_values():
    with pytest.raises(ValidationError, match="must not be empty string"):
        TaskOutput(
            output="Test output",
            source=DataSourceType.synthetic,
            source_properties={
                "adapter_name": "TestAdapter",
                "model_name": "",
                "model_provider": "OpenAI",
                "prompt_builder_name": "TestPromptBuilder",
            },
        )


def test_invalid_synthetic_task_output_non_string_values():
    with pytest.raises(ValidationError, match="Input should be a valid string"):
        TaskOutput(
            output="Test output",
            source=DataSourceType.synthetic,
            source_properties={
                "adapter_name": "TestAdapter",
                "model_name": "GPT-4",
                "model_provider": "OpenAI",
                "prompt_builder_name": 123,
            },
        )
