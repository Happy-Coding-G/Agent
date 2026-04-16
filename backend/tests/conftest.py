"""
Global test fixtures and module mocking.
"""
import sys
from types import ModuleType

# ======================================================================
# Mock missing ML dependencies before any imports
# ======================================================================

torch = ModuleType("torch")
torch.nn = ModuleType("torch.nn")
torch.nn.functional = ModuleType("torch.nn.functional")
torch.nn.init = ModuleType("torch.nn.init")

# Core torch classes/attributes needed by the codebase
torch.Tensor = type("Tensor", (), {})
torch.tensor = lambda *a, **k: None
torch.zeros = lambda *a, **k: None
torch.ones = lambda *a, **k: None
torch.rand = lambda *a, **k: None
torch.randn = lambda *a, **k: None
torch.FloatTensor = type("FloatTensor", (), {})
torch.LongTensor = type("LongTensor", (), {})
torch.stack = lambda *a, **k: None
torch.cat = lambda *a, **k: None

torch.nn.Module = type("Module", (), {"__init__": lambda self, *a, **k: None})
torch.nn.Embedding = type("Embedding", (), {})
torch.nn.Linear = type("Linear", (), {})
torch.nn.Dropout = type("Dropout", (), {})
torch.nn.BatchNorm1d = type("BatchNorm1d", (), {})
torch.nn.LayerNorm = type("LayerNorm", (), {})
torch.nn.ReLU = type("ReLU", (), {})
torch.nn.LeakyReLU = type("LeakyReLU", (), {})
torch.nn.Sigmoid = type("Sigmoid", (), {})
torch.nn.Softmax = type("Softmax", (), {})
torch.nn.Parameter = type("Parameter", (), {})
torch.nn.init.xavier_uniform_ = lambda x: x

torch.nn.functional.relu = lambda x, *a, **k: x
torch.nn.functional.leaky_relu = lambda x, *a, **k: x
torch.nn.functional.sigmoid = lambda x: x
torch.nn.functional.softmax = lambda x, *a, **k: x
torch.nn.functional.dropout = lambda x, *a, **k: x
torch.nn.functional.log_softmax = lambda x, *a, **k: x

sys.modules["torch"] = torch
sys.modules["torch.nn"] = torch.nn
sys.modules["torch.nn.functional"] = torch.nn.functional
sys.modules["torch.nn.init"] = torch.nn.init

torch_geometric = ModuleType("torch_geometric")
torch_geometric.nn = ModuleType("torch_geometric.nn")
torch_geometric.data = ModuleType("torch_geometric.data")

# torch_geometric mocks
tg_nn = torch_geometric.nn
tg_nn.SAGEConv = type("SAGEConv", (), {})
tg_nn.GATConv = type("GATConv", (), {})
tg_nn.GCNConv = type("GCNConv", (), {})
tg_nn.Linear = type("Linear", (), {})
tg_nn.global_mean_pool = lambda *a, **k: None
tg_nn.global_max_pool = lambda *a, **k: None
tg_nn.global_add_pool = lambda *a, **k: None
tg_nn.AttentionalAggregation = type("AttentionalAggregation", (), {})
tg_nn.Set2Set = type("Set2Set", (), {})
tg_nn.BatchNorm = type("BatchNorm", (), {})
tg_nn.LayerNorm = type("LayerNorm", (), {})
tg_nn.Sequential = type("Sequential", (), {})
tg_nn.MessagePassing = type("MessagePassing", (), {})

torch_geometric.data.Data = type("Data", (), {})
torch_geometric.data.Batch = type("Batch", (), {})
torch_geometric.data.DataLoader = type("DataLoader", (), {})
torch_geometric.data.Dataset = type("Dataset", (), {})
torch_geometric.data.InMemoryDataset = type("InMemoryDataset", (), {})
torch_geometric.loader = ModuleType("torch_geometric.loader")
torch_geometric.loader.DataLoader = type("DataLoader", (), {})
torch_geometric.loader.NeighborLoader = type("NeighborLoader", (), {})

sys.modules["torch_geometric"] = torch_geometric
sys.modules["torch_geometric.nn"] = torch_geometric.nn
sys.modules["torch_geometric.data"] = torch_geometric.data
sys.modules["torch_geometric.loader"] = torch_geometric.loader
