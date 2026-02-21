#!/usr/bin/env python3
"""
Inner Council Agent Registry
Central registry for all council member agents
"""

from typing import Dict, Type, Any
import importlib

# Agent registry
AGENT_REGISTRY = {}

def register_agent(agent_class: Type[Any]):
    """Register an agent class"""
    agent_name = agent_class.__name__.replace("Agent", "").lower()
    AGENT_REGISTRY[agent_name] = agent_class

def get_agent_class(agent_name: str) -> Type[Any]:
    """Get agent class by name"""
    return AGENT_REGISTRY.get(agent_name.lower())

def create_all_agents() -> Dict[str, Any]:
    """Create instances of all registered agents"""
    agents = {}
    for name, agent_class in AGENT_REGISTRY.items():
        try:
            agent = agent_class()
            agents[name] = agent
        except Exception as e:
            print(f"Error creating agent {name}: {e}")
    return agents

# Import all agent modules
from lex_fridman_agent import *
from tom_bilyeu_agent import *
from andrew_huberman_agent import *
from tim_ferriss_agent import *
from peter_attia_agent import *
from naval_ravikant_agent import *
from sam_harris_agent import *
from joe_rogan_agent import *
from elon_musk_agent import *
from vitalik_buterin_agent import *
from demis_hassabis_agent import *
from yann_lecun_agent import *
from geoffrey_hinton_agent import *
from shane_parrish_agent import *
from bret_weinstein_agent import *
from jordan_peterson_agent import *
from daniel_schmachtenberger_agent import *
from niall_ferguson_agent import *
from tyler_cowen_agent import *
from marc_andreessen_agent import *
from ben_shapiro_agent import *
from russell_brand_agent import *
from dave_rubin_agent import *
from candace_owens_agent import *
from tucker_carlson_agent import *
from the_joe_rogan_experience_agent import *
from lex_fridman_podcast_agent import *
from impact_theory_agent import *


# Register all agents
register_agent(LexFridmanAgent)
register_agent(TomBilyeuAgent)
register_agent(AndrewHubermanAgent)
register_agent(TimFerrissAgent)
register_agent(PeterAttiaAgent)
register_agent(NavalRavikantAgent)
register_agent(SamHarrisAgent)
register_agent(JoeRoganAgent)
register_agent(ElonMuskAgent)
register_agent(VitalikButerinAgent)
register_agent(DemisHassabisAgent)
register_agent(YannLecunAgent)
register_agent(GeoffreyHintonAgent)
register_agent(ShaneParrishAgent)
register_agent(BretWeinsteinAgent)
register_agent(JordanPetersonAgent)
register_agent(DanielSchmachtenbergerAgent)
register_agent(NiallFergusonAgent)
register_agent(TylerCowenAgent)
register_agent(MarcAndreessenAgent)
register_agent(BenShapiroAgent)
register_agent(RussellBrandAgent)
register_agent(DaveRubinAgent)
register_agent(CandaceOwensAgent)
register_agent(TuckerCarlsonAgent)
register_agent(TheJoeRoganExperienceAgent)
register_agent(LexFridmanPodcastAgent)
register_agent(ImpactTheoryAgent)
