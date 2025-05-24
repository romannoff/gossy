from langchain_huggingface import HuggingFaceEmbeddings
from scipy.spatial.distance import cosine


class EmbedChunks:
    def __init__(self, model_name):
        self.embedding_model = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"device": "cpu", "batch_size": 100})

    def __call__(self, text):
        embeddings = self.embedding_model.embed_documents(text)
        return {"text": text, "embeddings": embeddings}

    def get_nearest(self, line: str, vectors_dict: dict, top_k=1):

        line_vector = self([line])["embeddings"][0]

        vectors = list(vectors_dict.values())
        lines = list(vectors_dict.keys())

        cosine_similarity = [cosine(line_vector, vector) for vector in vectors]

        sort_lines = sorted(zip(lines, cosine_similarity), key=lambda x: x[1])[:5]

        if top_k == 1:
            return sort_lines[0][0], sort_lines[0][1]
        else:
            return sort_lines[:top_k][0], sort_lines[:top_k][1]
