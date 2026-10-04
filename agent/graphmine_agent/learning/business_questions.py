"""Authored application questions, with operation IDs kept out of user text.

These are synthetic task cards, not collected customer requests or independently
reviewed paraphrases. Each card keeps the source task's mathematical contract.
Training, validation and evaluation use separately authored wording banks.
"""

from __future__ import annotations

import re

VERSION = "business-questions-v1"

# Values are in train, validation, evaluation order. The key is a private label;
# only a value becomes the user request. Specific business criteria belong in
# a request; algorithm names and implementation procedures do not.
QUESTIONS = {
    "social_networks": {
        "maximal-cliques": (
            "Help me staff projects with ready-made teams. Show every team of at least three coworkers who have all worked with one another. Leave out a team if it is entirely included in another qualifying team, and give me the members' names.",
            "We are arranging collaboration workshops. Which sets of three or more employees already have a shared project history between any two members? Give me all the full sets by name, without separately listing smaller sets inside them.",
            "For our new workstreams, I want all the complete circles of colleagues with at least three people, where no two would be working together for the first time. Include names and keep only circles that cannot take another colleague under that rule.",
        ),
        "maximum-clique": (
            "I have one project to staff and want the biggest team that can start without introductions: everyone must have worked with everyone else. Give me one team and its headcount; I only need one option if several tie.",
            "We need one workshop cohort with as many employees as possible, all with prior project experience with each other. Who should be in it, and how many people is that? One of the equally large options is enough.",
            "Pick a single ready-made team for my assignment. Fit in as many colleagues as possible while making sure every two have worked together before. List their names and the team size; don't list tied alternatives.",
        ),
        "k-cliques": (
            "For three-person project assignments, list every possible trio of coworkers who have all worked with one another, even when they also belong to a larger established team.",
            "Each workshop exercise needs exactly three people with prior project experience with both of the others. What are all our possible trios? Keep trios from bigger established teams too.",
            "I have three seats per task force. Show every way to fill them with colleagues who already know one another through shared projects, including trios drawn from larger teams.",
        ),
        "k-core": (
            "For a peer-support pilot, who can participate if everyone must have at least {threshold} past collaborators among the participants? Include everyone who can meet that rule together; collaborators outside the pilot do not count.",
            "We are choosing a mentoring pool where each employee needs at least {threshold} familiar colleagues inside the pool. Give me the full eligible pool, counting only colleagues who also meet that same requirement.",
            "For a self-supporting work group, each member needs at least {threshold} previous teammates who are also members. Who can we include? Keep everyone who can qualify together, even if there are separate circles.",
        ),
        "betweenness-centrality": (
            "For handover planning, rank all coworkers by how often they would be the go-between when introductions between other coworkers use as few handoffs as possible. Use collaboration records, not claims about actual message traffic.",
            "Who are our likely coordination bottlenecks if people reach unfamiliar colleagues through the fewest possible introductions? Rank every employee using the recorded collaborations; this is a planning indicator, not measured workload.",
            "I am reviewing reliance on intermediaries. Order all colleagues by how often other people would need them along the most direct chains of introductions, counting one handoff per recorded collaboration.",
        ),
        "community-detection": (
            "Help me organize employee outreach around existing collaboration circles. Put each coworker in one suggested group based on who has worked together, treating every recorded collaboration equally. Show names and regions, but don't make region the grouping rule.",
            "For workshop planning, suggest separate employee groups from their collaboration history. Give everyone one group, treat all collaborations equally, and show their names and regions without using region to decide membership.",
            "I need a first draft of workstream groups that reflects existing working relationships. Assign each colleague to one group, with equal importance for every recorded collaboration. Include names and regions for context, not as membership rules.",
        ),
        "clarify": (
            "We need to improve collaboration. Which coworkers should I focus on first?",
            "I have time to speak to only a few employees. Who matters most for making our teams work better?",
            "Which people are the key ones for our next organizational change?",
        ),
        "broad_goal": (
            "Can you find the important teams for our reorganization?",
            "What are the best employee groups for next quarter's projects?",
            "Which groups of colleagues should management pay attention to?",
        ),
    },
    "fraud_detection": {
        "maximal-cliques": (
            "For an investigator's review queue, show every circle of at least three accounts where each account has exchanged payments with all the others. Keep the full circles rather than smaller circles inside them, and list the account names. A circle alone is not evidence of wrongdoing.",
            "Help me assemble case leads from payment records: list all complete payment circles with three or more accounts, so every two have paid one another. Omit circles wholly inside another qualifying circle. These are leads to review, not fraud findings.",
            "Our review team wants all the full mutual-payment circles of at least three accounts. Every account must have a recorded exchange with every other member, and no additional account could join on that basis. Name the members without declaring them fraudulent.",
        ),
        "maximum-clique": (
            "For one case review, pick the biggest set of accounts that have all exchanged payments with one another. List the accounts and how many there are; choose one set if several tie. Treat it as a review lead only.",
            "I can open one group review today. Find one payment circle with as many accounts as possible, provided every two accounts exchanged payments. Give me the names and count, with one option in a tie, without assuming wrongdoing.",
            "Choose a single largest mutual-payment circle for manual review. Everyone in it must have exchanged payments with everyone else. Show the account names and size; tied alternatives are unnecessary and the pattern is not proof of fraud.",
        ),
        "k-cliques": (
            "For three-account case reviews, list every trio whose members have all exchanged payments with one another, including trios inside larger circles. Do not label them fraudulent from this pattern alone.",
            "My analysts review three accounts at a time. Which trios have payment exchanges between any two members? Include every trio, even within bigger circles, as possible review leads only.",
            "Give me all three-account mutual-payment sets for our review queue. Keep sets that are part of bigger circles as well. The output should describe the recorded pattern, not infer misconduct.",
        ),
        "k-core": (
            "For a connected-case review, identify the full pool of accounts that can each have at least {threshold} payment partners inside the same pool. Only partners who also meet that requirement count; membership is not evidence of fraud.",
            "We want a case-review pool in which every account has exchanged payments with at least {threshold} other accounts in the pool. Include everyone who qualifies together, counting no outside partners and making no fraud claim.",
            "Which accounts can form a mutually supported review pool, with at least {threshold} payment partners per account among those included? Give me the full eligible pool; this is a structural lead, not a verdict.",
        ),
        "betweenness-centrality": (
            "For tracing possible intermediaries, rank all accounts by how often the fewest-transfer chains between other accounts would pass through them. Count payment links equally; this does not show where money actually traveled.",
            "Which accounts deserve attention as possible middlemen if we connect payers and payees through as few recorded payment relationships as possible? Rank all accounts as structural leads, not evidence of actual money movement or misconduct.",
            "I am reviewing dependence on payment intermediaries. Rank every account by how often it sits between other accounts on chains needing the fewest transfers. This is a relationship-based indicator, not a traced flow of funds.",
        ),
        "community-detection": (
            "Organize the accounts into separate review batches based on their payment relationships. Put each account in one batch and count every relationship equally. Show names and regions, but don't use regions to form batches or assume the batches are fraud rings.",
            "For allocating investigator workload, suggest separate account groups from who exchanges payments with whom. Give each account one group, treating relationships equally; include names and regions as context without using regions as the grouping rule.",
            "Help us break the payment-record review into suggested groups. Assign each account once, according to its payment connections, with all relationships treated equally. Display names and regions without grouping by region or inferring guilt.",
        ),
        "clarify": (
            "Which accounts should our fraud team investigate first?",
            "Where should we start looking for suspicious activity in these payment records?",
            "Who looks most risky in our account data?",
        ),
        "broad_goal": (
            "Find the important account groups for our investigation.",
            "Which payment groups are worth a closer look?",
            "What are the suspicious circles we should prioritize?",
        ),
    },
    "communications_infrastructure": {
        "maximal-cliques": (
            "For local service pods, list every set of at least three devices where every device can connect directly to all the others. Keep full pods rather than smaller sets inside them, and show the device names.",
            "We are planning direct-connect test pods. Give me all sets of three or more devices with a direct connection between any two. Skip smaller sets contained in another qualifying pod and list their names.",
            "For our service rollout, show all complete direct-connect device pods with at least three members. Nobody else should be able to join a pod while retaining a direct connection to every member. Include device names.",
        ),
        "maximum-clique": (
            "I need one test pod with as many devices as possible, all directly connected to one another. Give me one pod and its size; one is enough if several tie.",
            "For a single rollout trial, pick the biggest set of devices that can each reach every other device directly. Name them and give the count, choosing one option if there is a tie.",
            "Maximize the number of devices in one direct-connect trial pod. Every two devices must have a direct connection. Show one best pod and its size, without listing tied alternatives.",
        ),
        "k-cliques": (
            "For three-device test kits, list every trio whose devices are all directly connected to one another, including trios inside larger direct-connect pods.",
            "We test exactly three devices at a time and need a direct connection between any two in each test. What are all possible trios? Include ones from bigger pods too.",
            "Give our rollout team every three-device direct-connect combination, keeping trios even when a larger directly connected pod contains them.",
        ),
        "k-core": (
            "For a self-contained service pool, each device needs at least {threshold} direct connections to other devices in that pool. Give me the full pool that can satisfy this together; connections outside it do not count.",
            "Which devices can we keep in a service pool where each has at least {threshold} direct neighbors that also qualify for the pool? Include all qualifying devices, counting only connections within the pool.",
            "Find the full candidate pool for our connectivity trial: every included device must have at least {threshold} direct connections to other included devices. Outside connections cannot meet this requirement.",
        ),
        "betweenness-centrality": (
            "For capacity planning, rank every device by how often communication between other devices would pass through it when using the fewest connection hops. This is a planning indicator, not measured traffic.",
            "Which devices might become transit bottlenecks if communications take as few hops as possible? Rank all devices from the recorded connections without presenting the indicator as actual traffic volume.",
            "Help prioritize a network review by ranking devices that most often sit between other devices on the fewest-hop journeys. Show every device; do not claim this measures its real workload.",
        ),
        "community-detection": (
            "Suggest separate device groups for assigning service ownership, based on their connections. Give each device one group and treat each connection equally. Show names and regions, without using region as the grouping rule.",
            "For planning maintenance responsibilities, group devices by their connection patterns, assigning each device once. Count all connections equally and include names and regions as context, not as group boundaries.",
            "I need an initial division of devices into service areas from their recorded connections. Place each device in one group, giving all connections equal importance. Display names and regions without forming groups by region.",
        ),
        "clarify": (
            "Which devices should we prioritize for upgrades?",
            "Where should we invest first to make this network more reliable?",
            "Which equipment is most important to our service?",
        ),
        "broad_goal": (
            "Find the best device groups for our rollout.",
            "How should we organize these devices for the next maintenance cycle?",
            "Which parts of the network deserve their own service team?",
        ),
    },
    "bioinformatics": {
        "maximal-cliques": (
            "For follow-up assay batches, show every set of at least three proteins with a recorded physical interaction between any two members. Give the full sets rather than smaller sets inside them, and name the proteins. These are assay leads, not confirmed functional complexes.",
            "Help plan protein-assay batches from these records. List all sets of three or more proteins where each has physically interacted with all the others in an assay. Skip subsets of another qualifying batch and show names without claiming a confirmed complex.",
            "We want all the complete interaction circles of at least three proteins as possible follow-up batches. Every two must have an assay-recorded interaction, and no other protein can join under that rule. Name the members and keep biological conclusions tentative.",
        ),
        "maximum-clique": (
            "I can follow up one batch. Pick as many proteins as possible with an assay-recorded physical interaction between every two, and give their names and count. One option is enough in a tie; don't assume the batch is a functional complex.",
            "For one follow-up experiment, choose the biggest protein set whose members all physically interacted with one another in the recorded assays. Show names and size, with just one set if several tie. This selection alone does not validate a biological role.",
            "Choose a single largest batch of mutually interacting proteins for further investigation. Each interaction must be in these assay records. Give names and the batch size, without tied alternatives or claims of confirmed shared function.",
        ),
        "k-cliques": (
            "For three-protein follow-up assays, list every trio with a recorded physical interaction between any two members, including trios within bigger interaction circles. Treat them as candidates for investigation.",
            "Our experiment accepts exactly three proteins per batch. What are all the trios with assay-recorded interactions between every two? Keep trios from larger circles too, without claiming they share a confirmed function.",
            "Give us all three-protein batch candidates in which every two have physically interacted in the recorded assays. Include candidates within bigger interacting sets and avoid treating a match as biological validation.",
        ),
        "k-core": (
            "For a follow-up panel, each protein needs at least {threshold} recorded interaction partners that are also on the panel. Show the full eligible panel, counting only partners who meet the same rule; don't infer a shared biological function.",
            "Which proteins can belong to a panel where every member has at least {threshold} assay-recorded partners within the panel? Include everyone who can qualify together, with no outside partners counted and no claim of functional validation.",
            "Build the full candidate panel for follow-up assays so each included protein has at least {threshold} recorded interaction partners among those included. Treat this as an eligibility rule, not proof of biological importance.",
        ),
        "betweenness-centrality": (
            "For follow-up research, rank all proteins by how often they link other proteins along chains needing the fewest recorded interactions. Use this to suggest possible connectors to study, not to claim an actual biological pathway or essential function.",
            "Which proteins are potential connectors between others if we trace the most direct chains through the assay records? Rank them all, counting one step per interaction, without claiming that these chains are real biological signaling routes.",
            "Help prioritize investigation of connector proteins. Rank every protein by how often other pairs would be linked through it using the fewest recorded interactions. This indicator alone does not establish experimental success or biological importance.",
        ),
        "community-detection": (
            "Suggest separate protein batches for exploratory follow-up based on their recorded interactions. Put each protein in one batch and treat interactions equally. Show names and region annotations, without using region to form batches or claiming confirmed functions.",
            "For organizing follow-up research, divide the proteins into suggested interaction-based batches, giving each protein one batch. Count interactions equally; display names and region annotations for context, not as batching rules or biological conclusions.",
            "Give us an initial organization of proteins for follow-up work based on who interacted with whom. Assign each protein once, with equal weight for each recorded interaction. Show names and regions without grouping by region or claiming validated complexes.",
        ),
        "clarify": (
            "Which proteins should we test first in our next experiment?",
            "We have a limited assay budget. Which proteins matter most?",
            "What are the most promising proteins for our follow-up work?",
        ),
        "broad_goal": (
            "Find the important protein groups for our research program.",
            "Which protein sets would be best for the next study?",
            "What groups should our lab focus on?",
        ),
    },
    "recommendation_ecommerce": {
        "maximal-bicliques": (
            "For a bundle campaign, show customer groups of at least two people who all bought the same two or more products. I want every complete customer-and-product set, without breaking it into smaller sets when another customer or shared product can be included. List customers and products separately.",
            "Help me find shared-purchase audiences for a promotion: at least two customers must each have bought every item in a set of at least two products. Give all the full audiences with their full shared product sets, naming customers separately from products.",
            "We are planning bundle follow-ups from purchase history. List every full set of two or more customers and two or more products bought by each of those customers, retaining all customers and products that fit together. Keep the customer and product lists separate.",
        ),
    },
    "cybersecurity": {
        "temporal-motif-mining": (
            "For an incident review, find occasions when one machine contacted a second, the second then contacted a third, and the first then contacted that same third machine, all within 20 seconds. The machines must be different. Show their names and the event records in time order; this sequence alone does not prove an attack.",
            "Check the connection logs for this incident lead: a machine reaches another machine, that recipient next reaches a third, and the original sender then reaches the third. Use three different machines and no more than 20 seconds from start to finish. List the machines and matching event records, without treating a match as proof of intrusion.",
            "Our incident team wants the recorded instances of a three-machine contact sequence: sender to intermediary, intermediary to recipient, then sender to recipient. All three must be different and the sequence must finish within 20 seconds of starting. Show the machine names and event IDs in order as review leads only.",
        ),
        "four-host-chain": (
            "For incident review, count occasions when a connection passes from one machine to a second, then a third, then a fourth, within 20 seconds from the first contact to the last. All four machines must be different. Show the machines and event records too.",
            "Check for a possible four-machine relay in our logs: first machine to second, second to third, and third to fourth, in that order and within 20 seconds overall. Count matches and list the four different machines with their event records.",
            "Our security review needs the number and details of connection relays through four distinct machines, with each contacting the next in order. Allow at most 20 seconds from the first contact to the last and show the machines and events for each match.",
        ),
    },
}

CLARIFICATIONS = {
    "social_networks": "Are you trying to assemble people who have worked together, find people who connect different teams, or something else?",
    "fraud_detection": "Are you looking for mutually connected payment circles, possible intermediaries between accounts, or another pattern? Connections alone cannot establish fraud.",
    "communications_infrastructure": "Is the goal to find transit bottlenecks, plan directly connected test groups, or organize maintenance responsibilities?",
    "bioinformatics": "Are you looking for mutually interacting assay candidates or proteins that connect different interaction groups? These records alone cannot predict experimental success.",
}

# Cost is explicitly a recorded monetary attribute in the synthetic records.
# Weighted-score-as-distance cards are omitted: the records describe score as
# confidence, and disguising it as a business cost would change its meaning.
WEIGHTED = {
    "fraud_detection": (
        "For a payment-intermediary cost study, rank all accounts by how often they would connect other accounts when a chain is chosen for the lowest total recorded cost. Add the cost of each payment relationship along the chain; don't choose chains just by the number of transfers. This is a scenario calculation, not evidence of actual fund movement.",
        "Our cost review needs a ranking of accounts used as intermediaries on the cheapest chains between other accounts. Use the sum of the recorded payment-link costs to choose a chain. The ranking must reflect costs, not merely how many transfers it takes.",
        "Model cost-sensitive reliance on intermediaries for our payment review. Rank each account by how often cheapest-total-cost chains between other accounts pass through it, using the recorded cost on each relationship. This is not a tracing of actual money flows.",
    ),
    "communications_infrastructure": (
        "For cost-aware network planning, rank every device by how often it would carry communication between other devices if we always chose connections with the lowest total recorded cost. Add up the costs along a journey; using the fewest hops would answer a different question.",
        "Which devices would be our transit bottlenecks when communication follows the cheapest available journey? Rank every device using the sum of connection costs, not the number of hops, as the basis for choosing a journey.",
        "Our service-cost study needs a ranking of devices that sit between others on cheapest-total-cost journeys. Use the recorded cost of each connection, adding costs along the journey; don't substitute a fewest-hop ranking.",
    ),
}


def question_for(example, *, broad_goal=False):
    """Return an authored card or an explicit reason to omit a source task."""
    task = example["task"]
    index = {"train": 0, "validation": 1, "test": 2}[example["split"]]
    domain = example["domain"]
    if task["intent"]["requires_edge_weights"]:
        if task["intent"]["weight_attribute"] != "attributes.cost":
            return (
                None,
                "Confidence-as-distance has no supported business meaning in these task cards.",
            )
        if domain not in WEIGHTED:
            return None, "This domain has no authored practical cost-routing scenario."
        query = WEIGHTED[domain][index]
    else:
        kind = (
            "broad_goal"
            if broad_goal
            else "clarify"
            if task["behavior"] == "clarify"
            else "four-host-chain"
            if task["behavior"] == "unsupported"
            else task["operation_id"]
        )
        query = QUESTIONS[domain][kind][index].format(
            threshold=task["parameters"].get("requested_k")
        )
    clauses = []
    for criterion in task["filters"]:
        field, value = criterion["field"], criterion["value"]
        if criterion["operator"] != "eq":
            raise ValueError("No authored question for this filter operator")
        if field == "attributes.year":
            clauses.append(f"Base this only on relationships recorded in {value}.")
        elif field == "attributes.region":
            noun = {
                "social_networks": "coworkers",
                "fraud_detection": "accounts",
                "bioinformatics": "proteins",
                "communications_infrastructure": "devices",
            }[domain]
            clauses.append(
                f"Restrict this review to {noun} with region recorded as {value}."
            )
        elif field == "attributes.score":
            clauses.append(
                f"For this review, accept only relationships whose recorded score is exactly {value}; the separate ascore column is not the selection criterion."
            )
        else:
            raise ValueError("No authored business wording for this data field")
    return " ".join([*clauses, query]), None


def wording_issues(query):
    """A narrow implementation-jargon screen, not an independent meaning review."""
    issues = []
    if not 4 <= len(query.split()) <= 160:
        issues.append("Question is empty, too short, or too long for a task card")
    if re.search(
        r"\b(gpu|cuda|kernel|vertices|edges|cliques?|bicliques?|maximal|betweenness|modularity|k[- ]core|shortest[- ]paths?|adjacency)\b",
        query,
        re.IGNORECASE,
    ):
        issues.append("User question exposes an implementation or algorithm term")
    if re.search(
        r"\b(repeatedly remove|keep removing|peel off)\b", query, re.IGNORECASE
    ):
        issues.append("Question describes an implementation procedure")
    return issues
