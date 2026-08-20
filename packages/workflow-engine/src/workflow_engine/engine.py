import os
import json
import sqlite3
import logging
import uuid
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from abc import ABC, abstractmethod
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableSequence, RunnableLambda
from langchain_openai import ChatOpenAI
from langchain_community.llms import Ollama
from langchain_community.embeddings import BedrockEmbeddings, HuggingFaceEmbeddings
from langchain_community.chat_models import BedrockChat
from langchain.schema import HumanMessage
import streamlit as st
from dotenv import load_dotenv
import boto3
import re
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    filename='workflow.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Storage Backend Interface
class StorageBackend(ABC):
    @abstractmethod
    def save_state(self, workflow_id: str, state_data: Dict, version: int):
        pass

    @abstractmethod
    def load_state(self, workflow_id: str) -> Dict:
        pass

    @abstractmethod
    def log_step(self, workflow_id: str, step_id: str, substep_id: str, input_data: Dict, output_data: Dict,
                 prompt: str, retrieval_context: str, latency: float, token_usage: int,
                 success_status: bool, quality_score: float, evaluation_explanation: str):
        pass

    @abstractmethod
    def get_logs(self, workflow_id: str) -> List:
        pass

class SQLiteStorageBackend(StorageBackend):
    def __init__(self, db_path: str = "workflow_state.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS workflow_state (
                    workflow_id TEXT PRIMARY KEY,
                    state_data TEXT,
                    version INTEGER,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS step_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT,
                    step_id TEXT,
                    substep_id TEXT,
                    input_data TEXT,
                    output_data TEXT,
                    prompt TEXT,
                    retrieval_context TEXT,
                    timestamp TIMESTAMP,
                    latency REAL,
                    token_usage INTEGER,
                    success_status BOOLEAN,
                    quality_score REAL,
                    evaluation_explanation TEXT
                )
            ''')
            conn.commit()

    def save_state(self, workflow_id: str, state_data: Dict, version: int):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO workflow_state
                (workflow_id, state_data, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                workflow_id,
                json.dumps(state_data),
                version,
                datetime.now(),
                datetime.now()
            ))
            conn.commit()

    def load_state(self, workflow_id: str) -> Dict:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT state_data FROM workflow_state WHERE workflow_id = ?', (workflow_id,))
            result = cursor.fetchone()
            return json.loads(result[0]) if result else {}

    def log_step(self, workflow_id: str, step_id: str, substep_id: str, input_data: Dict, output_data: Dict,
                 prompt: str, retrieval_context: str, latency: float, token_usage: int,
                 success_status: bool, quality_score: float, evaluation_explanation: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO step_logs
                (workflow_id, step_id, substep_id, input_data, output_data, prompt, retrieval_context, timestamp,
                 latency, token_usage, success_status, quality_score, evaluation_explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                workflow_id,
                step_id,
                substep_id,
                json.dumps(input_data),
                json.dumps(output_data),
                prompt,
                retrieval_context,
                datetime.now(),
                latency,
                token_usage,
                success_status,
                quality_score,
                evaluation_explanation
            ))
            conn.commit()

    def get_logs(self, workflow_id: str) -> List:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM step_logs WHERE workflow_id = ?', (workflow_id,))
            return cursor.fetchall()

class JSONStorageBackend(StorageBackend):
    def __init__(self, state_file: str = "workflow_state.json", log_file: str = "step_logs.json"):
        self.state_file = state_file
        self.log_file = log_file
        self.init_files()

    def init_files(self):
        if not os.path.exists(self.state_file):
            with open(self.state_file, 'w') as f:
                json.dump({}, f)
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w') as f:
                json.dump([], f)

    def save_state(self, workflow_id: str, state_data: Dict, version: int):
        with open(self.state_file, 'r+') as f:
            states = json.load(f)
            states[workflow_id] = {
                "state_data": state_data,
                "version": version,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            f.seek(0)
            json.dump(states, f, indent=2)

    def load_state(self, workflow_id: str) -> Dict:
        with open(self.state_file, 'r') as f:
            states = json.load(f)
            return states.get(workflow_id, {}).get("state_data", {})

    def log_step(self, workflow_id: str, step_id: str, substep_id: str, input_data: Dict, output_data: Dict,
                 prompt: str, retrieval_context: str, latency: float, token_usage: int,
                 success_status: bool, quality_score: float, evaluation_explanation: str):
        with open(self.log_file, 'r+') as f:
            logs = json.load(f)
            logs.append({
                "workflow_id": workflow_id,
                "step_id": step_id,
                "substep_id": substep_id,
                "input_data": input_data,
                "output_data": output_data,
                "prompt": prompt,
                "retrieval_context": retrieval_context,
                "timestamp": datetime.now().isoformat(),
                "latency": latency,
                "token_usage": token_usage,
                "success_status": success_status,
                "quality_score": quality_score,
                "evaluation_explanation": evaluation_explanation
            })
            f.seek(0)
            json.dump(logs, f, indent=2)

    def get_logs(self, workflow_id: str) -> List:
        with open(self.log_file, 'r') as f:
            logs = json.load(f)
            return [log for log in logs if log["workflow_id"] == workflow_id]

# Configuration for LLM and Embeddings
class ModelConfig:
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "bedrock")  # Options: bedrock, openai, ollama
        self.embedding_provider = os.getenv("EMBEDDING_PROVIDER", "bedrock")  # Options: bedrock, huggingface
        self.bedrock_region = os.getenv("AWS_REGION", "us-east-1")
        self.bedrock_auth_token = os.getenv("BEDROCK_AUTH_TOKEN")
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def get_llm(self):
        if self.provider == "bedrock":
            bedrock = boto3.client(
                service_name='bedrock-runtime',
                region_name=self.bedrock_region,
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
            )
            return BedrockChat(
                client=bedrock,
                model_id="anthropic.claude-3-7-sonnet-20241022-v1:0",
                model_kwargs={"temperature": 0.7}
            )
        elif self.provider == "openai":
            return ChatOpenAI(
                openai_api_key=self.openai_api_key,
                model_name="gpt-4o",
                temperature=0.7
            )
        elif self.provider == "ollama":
            return Ollama(
                model="llama3",
                base_url=self.ollama_base_url,
                temperature=0.7
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def get_embeddings(self):
        if self.embedding_provider == "bedrock":
            bedrock = boto3.client(
                service_name='bedrock-runtime',
                region_name=self.bedrock_region,
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
            )
            return BedrockEmbeddings(
                client=bedrock,
                model_id="amazon.titan-embed-text-v1"
            )
        elif self.embedding_provider == "huggingface":
            return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        else:
            raise ValueError(f"Unsupported embedding provider: {self.embedding_provider}")

# SQLite Callback Handler
class SQLiteCallbackHandler(BaseCallbackHandler):
    def __init__(self, workflow_id: str, storage_backend: StorageBackend):
        self.workflow_id = workflow_id
        self.storage_backend = storage_backend

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        logger.info(f"Chain started: {serialized.get('id', 'unknown')} with inputs: {inputs}")

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs) -> None:
        metadata = kwargs.get("metadata", {})
        step_id = metadata.get("step_id", "")
        substep_id = metadata.get("substep_id", "")
        prompt = metadata.get("prompt", "")
        retrieval_context = metadata.get("retrieval_context", "")
        latency = metadata.get("latency", 0)
        token_usage = metadata.get("token_usage", 0)
        success_status = metadata.get("success_status", False)
        quality_score = metadata.get("quality_score", 0.0)
        evaluation_explanation = metadata.get("evaluation_explanation", "")

        self.storage_backend.log_step(
            workflow_id=self.workflow_id,
            step_id=step_id,
            substep_id=substep_id,
            input_data=kwargs.get("inputs", {}),
            output_data=outputs,
            prompt=prompt,
            retrieval_context=retrieval_context,
            latency=latency,
            token_usage=token_usage,
            success_status=success_status,
            quality_score=quality_score,
            evaluation_explanation=evaluation_explanation
        )

class WorkflowState:
    def __init__(self, workflow_id: str, storage_backend: StorageBackend):
        self.workflow_id = workflow_id
        self.storage_backend = storage_backend
        self.memory_buffer: Dict[str, Any] = self.load_state()
        self.version = 1

    def save_state(self):
        self.storage_backend.save_state(self.workflow_id, self.memory_buffer, self.version)

    def load_state(self) -> Dict:
        return self.storage_backend.load_state(self.workflow_id)

class Substep:
    def __init__(self, id: str, prompt_template: str, llm, embeddings, success_criteria: Dict,
                 use_rag: bool = False, web_search: bool = False, use_past_outputs: bool = False, relevance_threshold: float = 0.7):
        self.id = id
        self.prompt_template = ChatPromptTemplate.from_template(prompt_template)
        self.llm = llm
        self.embeddings = embeddings
        self.success_criteria = success_criteria
        self.use_rag = use_rag
        self.web_search = web_search
        self.use_past_outputs = use_past_outputs
        self.relevance_threshold = relevance_threshold
        self.vector_store = None

    def initialize_rag(self, documents: List[str]):
        if self.use_rag:
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
            chunks = text_splitter.split_text("\n".join(documents))
            docs = [Document(page_content=chunk) for chunk in chunks]
            self.vector_store = FAISS.from_documents(docs, self.embeddings)

    def evaluate_output(self, inputs: Dict, output: str) -> Dict:
        success_status = True
        quality_score = 1.0
        explanation = []

        # Rule-based checks
        if "output_format" in self.success_criteria:
            if self.success_criteria["output_format"] == "json":
                try:
                    json.loads(output)
                except json.JSONDecodeError:
                    success_status = False
                    quality_score *= 0.5
                    explanation.append("Output is not valid JSON.")

        if "keywords" in self.success_criteria:
            missing_keywords = [kw for kw in self.success_criteria["keywords"] if kw.lower() not in output.lower()]
            if missing_keywords:
                success_status = False
                quality_score *= 0.8
                explanation.append(f"Missing keywords: {', '.join(missing_keywords)}")

        if "max_length" in self.success_criteria:
            if len(output) > self.success_criteria["max_length"]:
                success_status = False
                quality_score *= 0.7
                explanation.append(f"Output exceeds max length of {self.success_criteria['max_length']} characters.")

        # LLM-based evaluation
        if "eval_prompt" in self.success_criteria:
            eval_prompt = ChatPromptTemplate.from_template(self.success_criteria["eval_prompt"])
            eval_chain = eval_prompt | self.llm
            eval_input = {
                "goal": self.success_criteria.get("goal", ""),
                "output": output,
                "input_data": inputs.get("input_data", "")
            }
            result = eval_chain.invoke(eval_input)
            try:
                score = float(result.content.split("\n")[0].strip())
                quality_score *= score
                explanation.append(result.content)
            except Exception as e:
                explanation.append(f"Evaluation failed: {str(e)}")

        return {
            "success_status": success_status,
            "quality_score": max(0.0, min(1.0, quality_score)),
            "evaluation_explanation": "\n".join(explanation) if explanation else "No issues detected."
        }

    def get_relevant_past_outputs(self, current_input: Dict, memory_buffer: Dict) -> Dict:
        if not self.use_past_outputs:
            return {}
        relevant_outputs = {}
        current_embedding = self.embeddings.embed_query(current_input.get("input_data", ""))
        for substep_id, output in memory_buffer.items():
            if substep_id != self.id and "result" in output:
                past_output_text = output["result"]
                past_embedding = self.embeddings.embed_query(past_output_text)
                similarity = cosine_similarity([current_embedding], [past_embedding])[0][0]
                if similarity >= self.relevance_threshold:
                    relevant_outputs[substep_id] = past_output_text
        return relevant_outputs

    def get_chain(self):
        def retrieve_context(inputs):
            if self.use_rag and self.vector_store:
                query = inputs.get("input_data", "")
                results = self.vector_store.similarity_search(query, k=3)
                context = "\n".join([doc.page_content for doc in results])
                inputs["retrieval_context"] = context
            return inputs

        def format_output(output):
            return {"result": output.content if hasattr(output, 'content') else str(output)}

        chain = RunnableSequence(
            RunnableLambda(retrieve_context) if self.use_rag else RunnableLambda(lambda x: x),
            self.prompt_template,
            self.llm,
            RunnableLambda(format_output)
        )
        return chain

    async def execute(self, input_data: Dict, memory_buffer: Dict, callback_handler: SQLiteCallbackHandler) -> Dict:
        try:
            start_time = time.time()
            # Include relevant past outputs
            past_outputs = self.get_relevant_past_outputs(input_data, memory_buffer)
            prompt_input = {**input_data, **memory_buffer, **past_outputs}
            chain = self.get_chain()

            if os.getenv("TEST_MODE") == "true":
                output = {"result": f"Mock response for substep {self.id}"}
                evaluation = {
                    "success_status": True,
                    "quality_score": 1.0,
                    "evaluation_explanation": "Mock evaluation successful."
                }
                latency = 0.1
                token_usage = len(str(prompt_input)) + len(str(output))
            else:
                prompt_text = self.prompt_template.format(**prompt_input)
                result = await chain.ainvoke(
                    prompt_input,
                    config={
                        "callbacks": [callback_handler],
                        "metadata": {
                            "step_id": input_data.get("step_id", ""),
                            "substep_id": self.id,
                            "prompt": prompt_text,
                            "retrieval_context": prompt_input.get("retrieval_context", ""),
                            "latency": 0,
                            "token_usage": 0
                        }
                    }
                )
                output = result
                evaluation = self.evaluate_output(prompt_input, output["result"])
                latency = time.time() - start_time
                token_usage = len(prompt_text) + len(str(output))

                # Update metadata for callback
                callback_handler.on_chain_end(
                    output,
                    inputs=prompt_input,
                    metadata={
                        "step_id": input_data.get("step_id", ""),
                        "substep_id": self.id,
                        "prompt": prompt_text,
                        "retrieval_context": prompt_input.get("retrieval_context", ""),
                        "success_status": evaluation["success_status"],
                        "quality_score": evaluation["quality_score"],
                        "evaluation_explanation": evaluation["evaluation_explanation"],
                        "latency": latency,
                        "token_usage": token_usage
                    }
                )

            memory_buffer[self.id] = output
            return {
                "output": output,
                "metrics": {
                    "latency": latency,
                    "token_usage": token_usage,
                    "quality_score": evaluation["quality_score"],
                    "success_status": evaluation["success_status"],
                    "evaluation_explanation": evaluation["evaluation_explanation"]
                }
            }
        except Exception as e:
            logger.error(f"Error in substep {self.id}: {str(e)}")
            evaluation = {
                "success_status": False,
                "quality_score": 0.0,
                "evaluation_explanation": f"Execution failed: {str(e)}"
            }
            return {
                "output": {"error": str(e)},
                "metrics": {
                    "latency": 0,
                    "token_usage": 0,
                    "quality_score": evaluation["quality_score"],
                    "success_status": evaluation["success_status"],
                    "evaluation_explanation": evaluation["evaluation_explanation"]
                }
            }

class Step:
    def __init__(self, id: str, substeps: List[Substep], success_criteria: Dict):
        self.id = id
        self.substeps = substeps
        self.success_criteria = success_criteria

    async def execute(self, input_data: Dict, workflow_state: WorkflowState, callback_handler: SQLiteCallbackHandler) -> Dict:
        output = {}
        substep_results = []
        for substep in self.substeps:
            input_data["step_id"] = self.id
            result = await substep.execute(input_data, workflow_state.memory_buffer, callback_handler)
            output[substep.id] = result
            substep_results.append(result["metrics"])
            input_data = result["output"]

        # Step-level evaluation
        step_evaluation = self.evaluate_step(substep_results, output)
        callback_handler.on_chain_end(
            output,
            inputs=input_data,
            metadata={
                "step_id": self.id,
                "substep_id": "",
                "prompt": "",
                "retrieval_context": "",
                "success_status": step_evaluation["success_status"],
                "quality_score": step_evaluation["quality_score"],
                "evaluation_explanation": step_evaluation["evaluation_ex palanation"],
                "latency": sum(r["latency"] for r in substep_results),
                "token_usage": sum(r["token_usage"] for r in substep_results)
            }
        )

        return {
            "output": output,
            "metrics": step_evaluation
        }

    def evaluate_step(self, substep_results: List[Dict], output: Dict) -> Dict:
        success_status = True
        quality_score = 1.0
        explanation = []

        # Aggregate substep results
        quality_scores = [r["quality_score"] for r in substep_results]
        avg_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
        all_succeeded = all(r["success_status"] for r in substep_results)

        if "min_quality_score" in self.success_criteria:
            if avg_quality_score < self.success_criteria["min_quality_score"]:
                success_status = False
                quality_score *= avg_quality_score
                explanation.append(f"Average quality score {avg_quality_score:.2f} below threshold {self.success_criteria['min_quality_score']}.")

        if self.success_criteria.get("all_substeps_must_succeed", False) and not all_succeeded:
            success_status = False
            quality_score *= 0.8
            explanation.append("Not all substeps succeeded.")

        # LLM-based evaluation
        if "eval_prompt" in self.success_criteria:
            eval_prompt = ChatPromptTemplate.from_template(self.success_criteria["eval_prompt"])
            eval_chain = eval_prompt | self.substeps[0].llm
            eval_input = {
                "goal": self.success_criteria.get("goal", ""),
                "output": json.dumps(output)
            }
            result = eval_chain.invoke(eval_input)
            try:
                score = float(result.content.split("\n")[0].strip())
                quality_score *= score
                explanation.append(result.content)
            except Exception as e:
                explanation.append(f"Step evaluation failed: {str(e)}")

        return {
            "success_status": success_status,
            "quality_score": max(0.0, min(1.0, quality_score)),
            "evaluation_explanation": "\n".join(explanation) if explanation else "No issues detected."
        }

class Workflow:
    def __init__(self, id: str, steps: List[Step], storage_backend: StorageBackend):
        self.id = id
        self.steps = steps
        self.state = WorkflowState(id, storage_backend)
        self.callback_handler = SQLiteCallbackHandler(id, storage_backend)

    async def execute(self, initial_input: Dict, resume_from_step: Optional[str] = None, max_retries: int = 1):
        self.state.load_state()
        start_idx = 0
        if resume_from_step:
            start_idx = next((i for i, step in enumerate(self.steps) if step.id == resume_from_step), 0)

        output = initial_input
        for step in self.steps[start_idx:]:
            retries = 0
            while retries <= max_retries:
                try:
                    result = await step.execute(output, self.state, self.callback_handler)
                    if result["metrics"]["success_status"]:
                        output = result["output"]
                        self.state.save_state()
                        break
                    else:
                        retries += 1
                        logger.warning(f"Step {step.id} failed evaluation, retry {retries}/{max_retries}")
                        if retries > max_retries:
                            logger.error(f"Step {step.id} failed after {max_retries} retries")
                            output = {"error": f"Step {step.id} failed evaluation"}
                            break
                except Exception as e:
                    logger.error(f"Step {step.id} failed: {str(e)}")
                    retries += 1
                    if retries > max_retries:
                        logger.error(f"Step {step.id} failed after {max_retries} retries: {str(e)}")
                        output = {"error": str(e)}
                        break
            if "error" in output:
                break
        return output

    def version(self) -> Dict:
        return {
            "workflow_id": self.id,
            "version": 1,
            "steps": [step.id for step in self.steps],
            "timestamp": datetime.now().isoformat()
        }

# Dashboard for observability
def show_dashboard(workflow_id: str, storage_backend: StorageBackend):
    st.title("AI Workflow Dashboard")
    logs = storage_backend.get_logs(workflow_id)

    if logs:
        st.subheader("Execution Flow")
        for log in logs:
            success = "✅" if log["success_status"] else "❌"
            st.write(f"Step: {log['step_id'] or 'N/A'}, Substep: {log['substep_id'] or 'N/A'}, "
                     f"Time: {log['timestamp']}, Latency: {log['latency']:.2f}s, Tokens: {log['token_usage']}, "
                     f"Success: {success}")
            st.json({
                "input": log["input_data"],
                "output": log["output_data"],
                "quality_score": log["quality_score"],
                "evaluation_explanation": 로그["evaluation_explanation"]
            })
    else:
        st.write("No logs available.")

# Example usage
if __name__ == "__main__":
    # Initialize storage backend
    storage_type = os.getenv("STORAGE_TYPE", "sqlite")
    if storage_type == "sqlite":
        storage_backend = SQLiteStorageBackend(db_path="workflow_state.db")
    elif storage_type == "json":
        storage_backend = JSONStorageBackend(state_file="workflow_state.json", log_file="step_logs.json")
    else:
        raise ValueError(f"Unsupported storage type: {storage_type}")

    # Initialize model configuration
    config = ModelConfig()
    llm = config.get_llm()
    embeddings = config.get_embeddings()

    # Define substeps with success criteria
    substep1 = Substep(
        id="substep1",
        prompt_template="Analyze the following input for sentiment: {input_data}\nPast outputs: {substep2}",
        llm=llm,
        embeddings=embeddings,
        success_criteria={
            "output_format": "json",
            "keywords": ["sentiment", "confidence"],
            "eval_prompt": "Evaluate if the output accurately identifies the sentiment of '{input_data}'.\nOutput: {output}\nReturn a score (0-1) and explanation.",
            "goal": "Identify sentiment with confidence score"
        },
        use_rag=True,
        use_past_outputs=True,
        relevance_threshold=0.7
    )
    substep1.initialize_rag(["Sample document: This is a positive review.", "Another document: Negative feedback detected."])

    substep2 = Substep(
        id="substep2",
        prompt_template="Summarize the sentiment analysis from {substep1.result}",
        llm=llm,
        embeddings=embeddings,
        success_criteria={
            "max_length": 100,
            "keywords": ["sentiment"],
            "eval_prompt": "Evaluate if the output is a concise summary (<100 words) of the sentiment analysis.\nOutput: {output}\nReturn a score (0-1) and explanation.",
            "goal": "Summarize sentiment analysis concisely"
        },
        use_rag=False,
        use_past_outputs=False
    )

    # Define step with success criteria
    step1 = Step(
        id="step1",
        substeps=[substep1, substep2],
        success_criteria={
            "min_quality_score": 0.8,
            "all_substeps_must_succeed": True,
            "eval_prompt": "Evaluate if the output forms a coherent sentiment report.\nOutput: {output}\nReturn a score (0-1) and explanation.",
            "goal": "Produce a coherent sentiment report"
        }
    )

    # Define workflow
    workflow = Workflow(id=str(uuid.uuid4()), steps=[step1], storage_backend=storage_backend)

    # Execute workflow
    import asyncio
    initial_input = {"input_data": "This product is amazing and works perfectly!"}
    result = asyncio.run(workflow.execute(initial_input))
    print(json.dumps(result, indent=2))

    # Run dashboard
    show_dashboard(workflow.id, storage_backend)