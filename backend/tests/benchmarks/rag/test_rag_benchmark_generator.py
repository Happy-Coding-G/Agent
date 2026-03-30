"""
RAG 检索评测大规模数据集生成器

基于 personalbench 数据格式，生成：
- 1000+ 文档块（向量）
- 3000+ 实体
- 100+ 测试查询
- 关系图谱数据

用于完整评测 5 层 RAG 检索架构
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import random
import hashlib
from typing import List, Dict, Any, Set, Tuple
from datetime import datetime, timedelta


# ============================================================================
# 基础数据模板 (来自 personalbench 格式扩展)
# ============================================================================

# 人物背景模板
PERSONA_TEMPLATES = [
    "A software engineer specializing in distributed systems and cloud computing.",
    "A data scientist working on machine learning models for natural language processing.",
    "A cybersecurity analyst focused on threat detection and vulnerability assessment.",
    "A product manager leading agile teams in the fintech industry.",
    "A research scientist studying climate change impacts on coastal ecosystems.",
    "A healthcare administrator managing hospital operations and patient care.",
    "A financial analyst specializing in quantitative trading strategies.",
    "A marketing director creating digital campaigns for tech startups.",
    "A civil engineer designing sustainable urban infrastructure.",
    "A teacher developing curriculum for STEM education.",
]

# 关系类型
RELATION_TYPES = [
    "colleague", "friend", "family", "neighbor", "classmate",
    "teammate", "mentor", "client", "partner", "supervisor"
]

# 话题类别
TOPIC_CATEGORIES = [
    "education", "career", "health", "finance", "technology",
    "travel", "hobbies", "family", "social", "news", "entertainment"
]

# 地点
LOCATIONS = [
    "New York", "London", "Tokyo", "Berlin", "Paris", "Sydney",
    "Toronto", "Singapore", "Dubai", "Mumbai", "Shanghai", "Seoul"
]

# 公司/组织
ORGANIZATIONS = [
    "Google", "Microsoft", "Amazon", "Meta", "Apple",
    "IBM", "Intel", "Cisco", "Oracle", "Salesforce",
    "Goldman Sachs", "Morgan Stanley", "JPMorgan", "Bank of America",
    "Harvard University", "MIT", "Stanford", "Oxford", "Cambridge"
]


# ============================================================================
# 数据生成器
# ============================================================================

class BenchmarkDataGenerator:
    """生成大规模 RAG 评测数据集"""

    def __init__(self, seed: int = 42):
        random.seed(seed)
        self.persons = []
        self.documents = []
        self.entities = []
        self.relations = []
        self.queries = []

    def generate_persons(self, num_persons: int = 100) -> List[Dict]:
        """生成人物数据"""
        persons = []
        for i in range(num_persons):
            person_id = f"person_{i:04d}"
            persona = random.choice(PERSONA_TEMPLATES)
            name = self._generate_name()

            person = {
                "node_id": i + 1,
                "person_id": person_id,
                "name": name,
                "persona": persona,
                "location": random.choice(LOCATIONS),
                "organization": random.choice(ORGANIZATIONS),
                "age": random.randint(25, 65),
                "interests": random.sample(TOPIC_CATEGORIES, k=random.randint(2, 5))
            }
            persons.append(person)

            # 为每个人物创建实体
            self.entities.append({
                "entity_id": f"entity_{person_id}_name",
                "entity_type": "PERSON",
                "entity_name": name,
                "person_id": person_id
            })
            self.entities.append({
                "entity_id": f"entity_{person_id}_org",
                "entity_type": "ORGANIZATION",
                "entity_name": person["organization"],
                "person_id": person_id
            })
            self.entities.append({
                "entity_id": f"entity_{person_id}_location",
                "entity_type": "LOCATION",
                "entity_name": person["location"],
                "person_id": person_id
            })

        self.persons = persons
        return persons

    def generate_documents(self, docs_per_person: int = 10) -> List[Dict]:
        """生成文档数据（对话、购买历史、交互记录等）"""
        documents = []
        doc_id = 0

        for person in self.persons:
            # 1. 基本信息文档
            bio_doc = self._create_biography_document(person)
            documents.append(bio_doc)
            self._extract_entities_from_doc(bio_doc)
            doc_id += 1

            # 2. 对话文档
            for _ in range(docs_per_person // 3):
                conv_doc = self._create_conversation_document(person, doc_id)
                documents.append(conv_doc)
                self._extract_entities_from_doc(conv_doc)
                doc_id += 1

            # 3. 购买历史
            purchase_doc = self._create_purchase_history_document(person, doc_id)
            documents.append(purchase_doc)
            self._extract_entities_from_doc(purchase_doc)
            doc_id += 1

            # 4. AI 交互记录
            for _ in range(docs_per_person // 3):
                ai_doc = self._create_ai_interaction_document(person, doc_id)
                documents.append(ai_doc)
                self._extract_entities_from_doc(ai_doc)
                doc_id += 1

        self.documents = documents
        return documents

    def generate_relations(self) -> List[Tuple]:
        """生成人物关系"""
        relations = []

        # 朋友关系
        for i, person in enumerate(self.persons):
            num_friends = random.randint(2, 6)
            friends = random.sample([p for j, p in enumerate(self.persons) if j != i], k=num_friends)
            for friend in friends:
                relations.append((
                    person["person_id"],
                    "friend",
                    friend["person_id"],
                    f"{person['name']} and {friend['name']} are friends"
                ))

        # 同事关系
        org_groups = {}
        for person in self.persons:
            org = person["organization"]
            if org not in org_groups:
                org_groups[org] = []
            org_groups[org].append(person)

        for org, members in org_groups.items():
            if len(members) >= 2:
                for i, person in enumerate(members):
                    colleagues = [m for j, m in enumerate(members) if j != i][:3]
                    for colleague in colleagues:
                        relations.append((
                            person["person_id"],
                            "colleague",
                            colleague["person_id"],
                            f"{person['name']} and {colleague['name']} work together at {org}"
                        ))

        # 家庭关系（随机添加）
        for _ in range(len(self.persons) // 5):
            p1, p2 = random.sample(self.persons, k=2)
            relations.append((
                p1["person_id"],
                "family",
                p2["person_id"],
                f"{p1['name']} and {p2['name']} are family members"
            ))

        self.relations = relations
        return relations

    def generate_queries(self, num_queries: int = 100) -> List[Dict]:
        """生成测试查询"""
        queries = []

        query_templates = [
            ("fact", "What is {entity}'s {attribute}?"),
            ("relationship", "What is the relationship between {entity1} and {entity2}?"),
            ("comparison", "How does {entity1}'s {attribute} compare to {entity2}'s?"),
            ("multi_hop", "Who is {entity1}'s {relation} and what is their {attribute}?"),
            ("aggregation", "How many {entity_type} are associated with {entity}?"),
            ("filter", "Which {entity_type} have {attribute} greater than {value}?"),
            ("temporal", "What happened to {entity} on {time}?"),
            ("recommendation", "What would you recommend for someone interested in {topic}?"),
        ]

        for i in range(num_queries):
            query_type = random.choice(query_templates)[0]
            query = self._generate_query_by_type(query_type, i)
            query["q_id"] = f"q_{i:05d}"
            queries.append(query)

        self.queries = queries
        return queries

    def _generate_name(self) -> str:
        """生成随机姓名"""
        first_names = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer",
                       "Michael", "Linda", "William", "Barbara", "David", "Elizabeth",
                       "Wei", "Chen", "Yuki", "Kenji", "Sofia", "Maria", "Anna", "Hans"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
                       "Miller", "Davis", "Wang", "Li", "Tanaka", "Kim", "Müller", "Rossi"]
        return f"{random.choice(first_names)} {random.choice(last_names)}"

    def _create_biography_document(self, person: Dict) -> Dict:
        """创建人物基本信息文档"""
        content = f"""
{person['name']} is a {person['age']}-year-old professional living in {person['location']}.
They work at {person['organization']}. {person['persona']}

Education Background:
- Bachelor's degree in Computer Science from MIT
- Master's in Data Science from Stanford

Career:
- Currently employed at {person['organization']} as a Senior Engineer
- Previously worked at Google for 3 years
- Has {random.randint(5, 15)} years of industry experience

Skills:
- Programming languages: Python, Java, JavaScript, Go
- Frameworks: React, Angular, Vue.js
- Databases: PostgreSQL, MongoDB, Redis

Interests:
- {', '.join(person['interests'])}
- Reading technical blogs
- Contributing to open source projects

Contact:
- Email: {person['name'].lower().replace(' ', '.')}@email.com
- LinkedIn: linkedin.com/in/{person['name'].lower().replace(' ', '-')}
"""
        return {
            "doc_id": f"doc_{person['person_id']}_bio",
            "content": content.strip(),
            "doc_type": "biography",
            "person_id": person["person_id"],
            "chunk_id": f"chunk_{person['person_id']}_bio_001"
        }

    def _create_conversation_document(self, person: Dict, doc_id: int) -> Dict:
        """创建对话文档"""
        topics = random.sample([
            "recent project updates", "team collaboration", "new technologies",
            "work-life balance", "industry trends", "career development",
            "workplace challenges", "upcoming conferences", "skill development"
        ], k=3)

        content = f"""
Conversation with {person['name']}
Date: {datetime.now().strftime('%Y/%m/%d')}

Topic: {topics[0]}
{person['name']}: I've been working on {topics[0]} recently. It's quite challenging but rewarding.
You: That sounds interesting. How's the progress?
{person['name']}: Good progress! We've achieved {random.randint(50, 90)}% of our goals.
You: Great to hear! Any blockers?
{person['name']}: The main challenge is coordinating with the {random.choice(['frontend', 'backend', 'DevOps'])} team.

Topic: {topics[1]}
{person['name']}: Regarding {topics[1]}, I think we should consider a new approach.
You: What's your proposal?
{person['name']}: We could implement {random.choice(['microservices', 'serverless', 'containerization'])} architecture.
You: That makes sense. Let's discuss with the team.

Topic: {topics[2]}
{person['name']}: On a different note, I've been exploring {topics[2]}.
You: Any findings you'd like to share?
{person['name']}: Yes, I wrote a summary on our internal wiki. Check it out!
"""
        return {
            "doc_id": f"doc_{person['person_id']}_conv_{doc_id}",
            "content": content.strip(),
            "doc_type": "conversation",
            "person_id": person["person_id"],
            "topics": topics,
            "chunk_id": f"chunk_{person['person_id']}_conv_{doc_id:04d}"
        }

    def _create_purchase_history_document(self, person: Dict, doc_id: int) -> Dict:
        """创建购买历史文档"""
        items = []
        for _ in range(random.randint(3, 8)):
            item = random.choice([
                "Laptop", "Smartphone", "Headphones", "Monitor", "Keyboard", "Mouse",
                "Tablet", "Smartwatch", "Camera", "Speaker", "Charger", "Cable"
            ])
            brand = random.choice(["Apple", "Samsung", "Sony", "Dell", "Lenovo", "Logitech"])
            price = random.randint(50, 2000)
            date = (datetime.now() - timedelta(days=random.randint(1, 365))).strftime('%Y-%m-%d')
            items.append(f"- {brand} {item} (${price}) - {date}")

        content = f"""
Purchase History for {person['name']}
{'=' * 50}

Total Purchases: {len(items)}
{'=' * 50}

{chr(10).join(items)}

Recent Purchase Summary:
- Most purchased category: Electronics
- Average purchase amount: ${random.randint(100, 500)}
- Last purchase: {items[0] if items else 'N/A'}
"""
        return {
            "doc_id": f"doc_{person['person_id']}_purchase_{doc_id}",
            "content": content.strip(),
            "doc_type": "purchase_history",
            "person_id": person["person_id"],
            "chunk_id": f"chunk_{person['person_id']}_purchase_{doc_id:04d}"
        }

    def _create_ai_interaction_document(self, person: Dict, doc_id: int) -> Dict:
        """创建AI交互文档"""
        interactions = []
        for i in range(random.randint(3, 6)):
            question = random.choice([
                f"Can you explain {random.choice(['machine learning', 'deep learning', 'NLP'])} concepts?",
                f"What's the best way to optimize {random.choice(['database', 'API', 'frontend'])} performance?",
                f"How do I implement {random.choice(['authentication', 'caching', 'testing'])} in my project?",
                f"What are the latest trends in {random.choice(['AI', 'cloud', 'security'])}?",
                f"Can you help me debug this code issue?"
            ])
            answer = f"Here's a detailed explanation and recommendations for your question about {random.choice(['implementation', 'optimization', 'best practices'])}..."

            interactions.append(f"""
Question {i+1}: {question}
Answer: {answer}
Confidence: {random.randint(85, 99)}%
""")

        content = f"""
AI Interaction History for {person['name']}
{'=' * 50}
Session Date: {datetime.now().strftime('%Y/%m/%d')}

{chr(10).join(interactions)}

Interaction Statistics:
- Total interactions: {len(interactions)}
- Average session length: {random.randint(10, 30)} minutes
- Topics discussed: {', '.join(random.sample(['technology', 'career', 'education', 'finance', 'health'], k=3))}
"""
        return {
            "doc_id": f"doc_{person['person_id']}_ai_{doc_id}",
            "content": content.strip(),
            "doc_type": "ai_interaction",
            "person_id": person["person_id"],
            "chunk_id": f"chunk_{person['person_id']}_ai_{doc_id:04d}"
        }

    def _extract_entities_from_doc(self, doc: Dict) -> None:
        """从文档中提取实体"""
        content = doc.get("content", "")

        # 提取人名（简单模式匹配）
        words = content.split()
        for i, word in enumerate(words):
            if word[0].isupper() and len(word) > 2 and i > 0 and words[i-1][-1] in '.!?':
                entity_name = word.strip('.,!?')
                if entity_name not in ["Date", "Topic", "Question", "Answer", "Total", "Summary"]:
                    self.entities.append({
                        "entity_id": f"entity_{hashlib.md5(entity_name.encode()).hexdigest()[:8]}",
                        "entity_type": "MENTION",
                        "entity_name": entity_name,
                        "doc_id": doc["doc_id"]
                    })

    def _generate_query_by_type(self, query_type: str, index: int) -> Dict:
        """根据类型生成查询"""
        person = random.choice(self.persons) if self.persons else {"name": "John Doe", "person_id": "person_0000"}

        templates = {
            "fact": {
                "query": f"What is {person['name']}'s occupation and where do they work?",
                "type": "fact",
                "difficulty": random.choice(["easy", "medium"]),
                "requires_graph": False
            },
            "relationship": {
                "query": f"Who are the colleagues of {person['name']} at {person['organization']}?",
                "type": "relationship",
                "difficulty": "medium",
                "requires_graph": True
            },
            "comparison": {
                "query": f"How does {person['name']}'s work at {person['organization']} compare to others in similar roles?",
                "type": "comparison",
                "difficulty": "hard",
                "requires_graph": True
            },
            "multi_hop": {
                "query": f"What is the name of {person['name']}'s colleague who works in the same team and what projects are they working on?",
                "type": "multi_hop",
                "difficulty": "hard",
                "requires_graph": True
            },
            "aggregation": {
                "query": f"How many people work at {person['organization']} and what are their roles?",
                "type": "aggregation",
                "difficulty": "medium",
                "requires_graph": True
            },
            "filter": {
                "query": f"Which professionals in {person['location']} have more than 5 years of experience?",
                "type": "filter",
                "difficulty": "medium",
                "requires_graph": False
            },
            "temporal": {
                "query": f"What recent AI interactions has {person['name']} had about machine learning?",
                "type": "temporal",
                "difficulty": "easy",
                "requires_graph": False
            },
            "recommendation": {
                "query": f"Based on {person['name']}'s interests in {', '.join(person.get('interests', ['technology'])[:2])}, what would you recommend?",
                "type": "recommendation",
                "difficulty": "medium",
                "requires_graph": False
            }
        }

        template = templates.get(query_type, templates["fact"])
        return {
            "query": template["query"],
            "type": template["type"],
            "difficulty": template["difficulty"],
            "requires_graph": template["requires_graph"],
            "person_id": person["person_id"]
        }


# ============================================================================
# 数据集构建
# ============================================================================

def generate_large_scale_dataset() -> Dict[str, Any]:
    """生成大规模评测数据集"""

    generator = BenchmarkDataGenerator(seed=42)

    print("生成人物数据...")
    persons = generator.generate_persons(num_persons=100)
    print(f"  - 生成 {len(persons)} 个人物")

    print("生成文档数据...")
    documents = generator.generate_documents(docs_per_person=12)
    print(f"  - 生成 {len(documents)} 个文档")

    print("生成关系数据...")
    relations = generator.generate_relations()
    print(f"  - 生成 {len(relations)} 条关系")

    print("生成查询数据...")
    queries = generator.generate_queries(num_queries=100)
    print(f"  - 生成 {len(queries)} 个查询")

    # 统计数据
    total_entities = len(generator.entities)

    print("\n" + "=" * 60)
    print("数据集统计")
    print("=" * 60)
    print(f"人物数量: {len(persons)}")
    print(f"文档数量: {len(documents)}")
    print(f"实体数量: {total_entities}")
    print(f"关系数量: {len(relations)}")
    print(f"查询数量: {len(queries)}")

    # 验证规模
    assert len(documents) >= 1000, f"文档数量不足: {len(documents)} < 1000"
    assert total_entities >= 3000, f"实体数量不足: {total_entities} < 3000"

    return {
        "persons": persons,
        "documents": documents,
        "entities": generator.entities,
        "relations": relations,
        "queries": queries,
        "metadata": {
            "num_persons": len(persons),
            "num_documents": len(documents),
            "num_entities": total_entities,
            "num_relations": len(relations),
            "num_queries": len(queries),
            "generated_at": datetime.now().isoformat(),
            "version": "1.0"
        }
    }


# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("RAG 检索评测大规模数据集生成器")
    print("=" * 60)

    dataset = generate_large_scale_dataset()

    # 保存数据集
    output_path = Path(__file__).parent / "rag_benchmark_data.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"\n数据集已保存至: {output_path}")
    print(f"文件大小: {output_path.stat().st_size / 1024 / 1024:.2f} MB")
