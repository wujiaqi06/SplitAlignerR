#include <Rcpp.h>

#include "numeric_policy.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <iomanip>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {

struct Node {
  std::vector<int> children;
  std::string label;
  bool has_length = false;
  std::string length_token;
  int branch_number = 0;
};

struct CanonicalSplit {
  std::string key;
  std::vector<std::string> side_a;
  std::vector<std::string> side_b;
};

struct EdgeRecord {
  int node_index = -1;
  int branch_number = 0;
  std::string branch_id;
  std::string branch_type;
  CanonicalSplit split;
};

class NewickParser {
 public:
  explicit NewickParser(std::string text) : text_(std::move(text)) {}

  int parse() {
    skip_trivia();
    if (at_end()) {
      fail("empty tree string");
    }
    const int root = parse_subtree();
    skip_trivia();
    expect(';');
    skip_trivia();
    if (!at_end()) {
      fail("extra content after the terminating semicolon");
    }
    return root;
  }

  const std::vector<Node>& nodes() const {
    return nodes_;
  }

  int annotation_count() const {
    return annotation_count_;
  }

 private:
  std::string text_;
  std::size_t position_ = 0;
  std::vector<Node> nodes_;
  int annotation_count_ = 0;

  bool at_end() const {
    return position_ >= text_.size();
  }

  char peek() const {
    return at_end() ? '\0' : text_[position_];
  }

  [[noreturn]] void fail(const std::string& message) const {
    throw std::runtime_error(
      "Newick parse error at byte " + std::to_string(position_) +
      ": " + message
    );
  }

  void expect(char expected) {
    if (peek() != expected) {
      const std::string actual = at_end()
        ? "end of input"
        : std::string("'") + peek() + "'";
      fail(std::string("expected '") + expected + "' but found " + actual);
    }
    ++position_;
  }

  void skip_comment() {
    expect('[');
    int depth = 1;
    while (!at_end() && depth > 0) {
      const char ch = text_[position_++];
      if (ch == '[') {
        ++depth;
      } else if (ch == ']') {
        --depth;
      }
    }
    if (depth != 0) {
      fail("unterminated annotation block");
    }
    ++annotation_count_;
  }

  void skip_trivia() {
    bool advanced = true;
    while (advanced) {
      advanced = false;
      while (!at_end() &&
             std::isspace(static_cast<unsigned char>(peek())) != 0) {
        ++position_;
        advanced = true;
      }
      if (peek() == '[') {
        skip_comment();
        advanced = true;
      }
    }
  }

  bool begins_label() const {
    if (at_end()) {
      return false;
    }
    const char ch = peek();
    return ch != ':' && ch != ',' && ch != ')' && ch != '(' &&
      ch != ';' && ch != '[';
  }

  std::string parse_quoted_label() {
    const char quote = peek();
    ++position_;
    std::string label;
    while (!at_end()) {
      const char ch = text_[position_++];
      if (ch != quote) {
        label.push_back(ch);
        continue;
      }
      if (!at_end() && peek() == quote) {
        label.push_back(quote);
        ++position_;
        continue;
      }
      return label;
    }
    fail("unterminated quoted label");
  }

  std::string parse_unquoted_token() {
    const std::size_t start = position_;
    while (!at_end()) {
      const char ch = peek();
      if (std::isspace(static_cast<unsigned char>(ch)) != 0 ||
          ch == ':' || ch == ',' || ch == '(' || ch == ')' ||
          ch == ';' || ch == '[' || ch == ']') {
        break;
      }
      ++position_;
    }
    return text_.substr(start, position_ - start);
  }

  std::string parse_label(bool required) {
    std::string label;
    if (peek() == '\'' || peek() == '"') {
      label = parse_quoted_label();
    } else if (begins_label()) {
      label = parse_unquoted_token();
    }
    if (required && label.empty()) {
      fail("missing terminal taxon label");
    }
    return label;
  }

  std::string parse_branch_token() {
    const std::string token = parse_unquoted_token();
    if (token.empty()) {
      fail("missing branch-length token after ':'");
    }
    return token;
  }

  int parse_subtree() {
    skip_trivia();
    Node node;

    if (peek() == '(') {
      ++position_;
      node.children.push_back(parse_subtree());
      while (true) {
        skip_trivia();
        if (peek() != ',') {
          break;
        }
        ++position_;
        node.children.push_back(parse_subtree());
      }
      if (node.children.size() < 2U) {
        fail("an internal node must contain at least two children");
      }
      skip_trivia();
      expect(')');
      skip_trivia();
      node.label = parse_label(false);
    } else {
      node.label = parse_label(true);
    }

    skip_trivia();
    if (peek() == ':') {
      ++position_;
      skip_trivia();
      node.length_token = parse_branch_token();
      node.has_length = true;
    }
    skip_trivia();

    nodes_.push_back(std::move(node));
    return static_cast<int>(nodes_.size()) - 1;
  }
};

void collect_leaf_nodes(const std::vector<Node>& nodes, int node_index,
                        std::vector<int>& output) {
  const Node& node = nodes[node_index];
  if (node.children.empty()) {
    output.push_back(node_index);
    return;
  }
  for (int child : node.children) {
    collect_leaf_nodes(nodes, child, output);
  }
}

void collect_internal_postorder(const std::vector<Node>& nodes, int node_index,
                                int root_index, std::vector<int>& output) {
  const Node& node = nodes[node_index];
  for (int child : node.children) {
    collect_internal_postorder(nodes, child, root_index, output);
  }
  if (!node.children.empty() && node_index != root_index) {
    output.push_back(node_index);
  }
}

std::vector<std::string> descendant_tips(const std::vector<Node>& nodes,
                                         int node_index) {
  const Node& node = nodes[node_index];
  if (node.children.empty()) {
    return {node.label};
  }
  std::vector<std::string> tips;
  for (int child : node.children) {
    std::vector<std::string> child_tips = descendant_tips(nodes, child);
    tips.insert(tips.end(), child_tips.begin(), child_tips.end());
  }
  std::sort(tips.begin(), tips.end());
  return tips;
}

std::string join(const std::vector<std::string>& values,
                 const std::string& separator) {
  std::ostringstream out;
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i > 0U) {
      out << separator;
    }
    out << values[i];
  }
  return out.str();
}

bool legacy_safe_label(const std::string& label) {
  return label.find('|') == std::string::npos &&
    label.find("..") == std::string::npos &&
    label.find(':') == std::string::npos &&
    !label.empty() && label.front() != '.' && label.back() != '.';
}

std::string hex_encode(const std::string& value) {
  std::ostringstream out;
  out << std::hex << std::setfill('0');
  for (unsigned char byte : value) {
    out << std::setw(2) << static_cast<unsigned int>(byte);
  }
  return out.str();
}

std::string structured_set_key(const std::vector<std::string>& taxa) {
  std::vector<std::string> encoded;
  encoded.reserve(taxa.size());
  for (const std::string& taxon : taxa) {
    encoded.push_back(hex_encode(taxon));
  }
  std::sort(encoded.begin(), encoded.end());
  return "HS1:" + join(encoded, ",");
}

CanonicalSplit canonical_split(std::vector<std::string> left,
                               std::vector<std::string> right) {
  std::sort(left.begin(), left.end());
  std::sort(right.begin(), right.end());
  bool legacy_safe = true;
  for (const std::string& label : left) {
    legacy_safe = legacy_safe && legacy_safe_label(label);
  }
  for (const std::string& label : right) {
    legacy_safe = legacy_safe && legacy_safe_label(label);
  }

  std::string left_key;
  std::string right_key;
  std::string prefix;
  if (legacy_safe) {
    left_key = join(left, "..");
    right_key = join(right, "..");
  } else {
    left_key = structured_set_key(left);
    right_key = structured_set_key(right);
    prefix = "HX1:";
  }

  if (left_key <= right_key) {
    return {prefix + left_key + "||" + right_key, left, right};
  }
  return {prefix + right_key + "||" + left_key, right, left};
}

Rcpp::DataFrame diagnostic_table(int reference_lengths, int root_lengths,
                                 int internal_labels, int annotations,
                                 int multifurcations, int duplicate_aliases) {
  return Rcpp::DataFrame::create(
    Rcpp::Named("code") = Rcpp::CharacterVector::create(
      "IGNORED_REFERENCE_BRANCH_LENGTH",
      "IGNORED_ROOT_LENGTH",
      "IGNORED_INTERNAL_LABEL",
      "IGNORED_ANNOTATION_BLOCK",
      "MULTIFURCATING_REFERENCE_NODE",
      "DUPLICATE_UNROOTED_SPLIT_ALIAS"
    ),
    Rcpp::Named("severity") = Rcpp::CharacterVector::create(
      "INFO", "INFO", "INFO", "INFO", "INFO", "INFO"
    ),
    Rcpp::Named("count") = Rcpp::IntegerVector::create(
      reference_lengths, root_lengths, internal_labels, annotations,
      multifurcations, duplicate_aliases
    ),
    Rcpp::Named("message") = Rcpp::CharacterVector::create(
      "Reference-tree branch lengths were parsed and intentionally ignored",
      "A representation-root length was parsed and intentionally ignored",
      "Internal labels/support values were parsed and intentionally ignored",
      "Bracket annotation blocks were parsed and intentionally ignored",
      "Reference multifurcations were retained without binary refinement",
      "Equivalent root-representation edges share one unrooted coordinate"
    ),
    Rcpp::Named("stringsAsFactors") = false
  );
}

}  // namespace

// [[Rcpp::export]]
Rcpp::List cpp_validate_species_tree(std::string newick) {
  NewickParser parser(std::move(newick));
  const int root_index = parser.parse();
  std::vector<Node> nodes = parser.nodes();

  std::vector<int> leaf_nodes;
  collect_leaf_nodes(nodes, root_index, leaf_nodes);
  if (leaf_nodes.size() < 2U) {
    Rcpp::stop("Species tree must contain at least two terminal taxa.");
  }

  std::set<std::string> seen_tips;
  Rcpp::CharacterVector tip_labels(leaf_nodes.size());
  for (std::size_t i = 0; i < leaf_nodes.size(); ++i) {
    const std::string& label = nodes[leaf_nodes[i]].label;
    if (!seen_tips.insert(label).second) {
      Rcpp::stop("Duplicate terminal taxon `%s`.", label);
    }
    tip_labels[i] = label;
    nodes[leaf_nodes[i]].branch_number = static_cast<int>(i) + 1;
  }

  std::vector<int> internal_nodes;
  collect_internal_postorder(nodes, root_index, root_index, internal_nodes);
  int branch_counter = static_cast<int>(leaf_nodes.size());
  for (int node_index : internal_nodes) {
    nodes[node_index].branch_number = ++branch_counter;
  }

  std::vector<std::string> all_tips(seen_tips.begin(), seen_tips.end());
  std::vector<EdgeRecord> edges;
  edges.reserve(nodes.size() - 1U);
  for (std::size_t node_index = 0; node_index < nodes.size(); ++node_index) {
    if (static_cast<int>(node_index) == root_index) {
      continue;
    }
    std::vector<std::string> left = descendant_tips(
      nodes, static_cast<int>(node_index)
    );
    std::set<std::string> left_set(left.begin(), left.end());
    std::vector<std::string> right;
    for (const std::string& tip : all_tips) {
      if (left_set.find(tip) == left_set.end()) {
        right.push_back(tip);
      }
    }
    const int number = nodes[node_index].branch_number;
    edges.push_back({
      static_cast<int>(node_index),
      number,
      "B" + std::to_string(number),
      nodes[node_index].children.empty() ? "terminal" : "internal",
      canonical_split(std::move(left), std::move(right))
    });
  }

  std::map<std::string, std::vector<std::size_t>> groups;
  for (std::size_t i = 0; i < edges.size(); ++i) {
    groups[edges[i].split.key].push_back(i);
  }

  struct AxisRecord {
    std::size_t winner;
    std::vector<std::size_t> members;
  };
  std::vector<AxisRecord> axis;
  int duplicate_aliases = 0;
  for (const auto& item : groups) {
    std::vector<std::size_t> members = item.second;
    std::sort(members.begin(), members.end(), [&](std::size_t a, std::size_t b) {
      return edges[a].branch_number < edges[b].branch_number;
    });
    duplicate_aliases += static_cast<int>(members.size()) - 1;
    axis.push_back({members.front(), members});
  }
  std::sort(axis.begin(), axis.end(), [&](const AxisRecord& a,
                                         const AxisRecord& b) {
    return edges[a.winner].branch_number < edges[b.winner].branch_number;
  });

  const R_xlen_t coordinate_count = static_cast<R_xlen_t>(axis.size());
  Rcpp::CharacterVector coordinate_id(coordinate_count);
  Rcpp::CharacterVector canonical_keys(coordinate_count);
  Rcpp::CharacterVector branch_type(coordinate_count);
  Rcpp::CharacterVector alias_text(coordinate_count);
  Rcpp::IntegerVector side_a_size(coordinate_count);
  Rcpp::IntegerVector side_b_size(coordinate_count);
  Rcpp::List side_a_taxa(coordinate_count);
  Rcpp::List side_b_taxa(coordinate_count);
  Rcpp::List primitive_aliases(coordinate_count);
  Rcpp::CharacterVector note(coordinate_count);

  for (R_xlen_t i = 0; i < coordinate_count; ++i) {
    const AxisRecord& record = axis[static_cast<std::size_t>(i)];
    const EdgeRecord& winner = edges[record.winner];
    std::vector<std::string> aliases;
    for (std::size_t member : record.members) {
      aliases.push_back(edges[member].branch_id);
    }
    coordinate_id[i] = winner.branch_id;
    canonical_keys[i] = winner.split.key;
    branch_type[i] = winner.branch_type;
    alias_text[i] = join(aliases, "|");
    side_a_size[i] = static_cast<int>(winner.split.side_a.size());
    side_b_size[i] = static_cast<int>(winner.split.side_b.size());
    side_a_taxa[i] = Rcpp::wrap(winner.split.side_a);
    side_b_taxa[i] = Rcpp::wrap(winner.split.side_b);
    primitive_aliases[i] = Rcpp::wrap(aliases);
    note[i] = aliases.size() > 1U
      ? "lowest B alias retained for duplicate unrooted split"
      : "";
  }
  side_a_taxa.attr("class") = "AsIs";
  side_b_taxa.attr("class") = "AsIs";
  primitive_aliases.attr("class") = "AsIs";

  int reference_lengths = 0;
  int internal_labels = 0;
  int multifurcations = 0;
  for (std::size_t i = 0; i < nodes.size(); ++i) {
    if (static_cast<int>(i) != root_index && nodes[i].has_length) {
      ++reference_lengths;
    }
    if (!nodes[i].children.empty() && !nodes[i].label.empty()) {
      ++internal_labels;
    }
    const std::size_t graph_degree = nodes[i].children.size() +
      (static_cast<int>(i) == root_index ? 0U : 1U);
    if (!nodes[i].children.empty() && graph_degree > 3U) {
      ++multifurcations;
    }
  }
  const int root_lengths = nodes[root_index].has_length ? 1 : 0;
  const int root_degree = static_cast<int>(nodes[root_index].children.size());

  Rcpp::DataFrame coordinates = Rcpp::DataFrame::create(
    Rcpp::Named("coordinate_id") = coordinate_id,
    Rcpp::Named("canonical_split") = canonical_keys,
    Rcpp::Named("branch_type") = branch_type,
    Rcpp::Named("primitive_alias_text") = alias_text,
    Rcpp::Named("side_a_size") = side_a_size,
    Rcpp::Named("side_b_size") = side_b_size,
    Rcpp::Named("side_a_taxa") = side_a_taxa,
    Rcpp::Named("side_b_taxa") = side_b_taxa,
    Rcpp::Named("primitive_aliases") = primitive_aliases,
    Rcpp::Named("note") = note,
    Rcpp::Named("stringsAsFactors") = false
  );

  return Rcpp::List::create(
    Rcpp::Named("valid") = true,
    Rcpp::Named("tip_labels") = tip_labels,
    Rcpp::Named("coordinates") = coordinates,
    Rcpp::Named("diagnostics") = diagnostic_table(
      reference_lengths, root_lengths, internal_labels,
      parser.annotation_count(), multifurcations, duplicate_aliases
    ),
    Rcpp::Named("metadata") = Rcpp::List::create(
      Rcpp::Named("tip_count") = static_cast<int>(leaf_nodes.size()),
      Rcpp::Named("node_count") = static_cast<int>(nodes.size()),
      Rcpp::Named("primitive_alias_count") = branch_counter,
      Rcpp::Named("coordinate_count") = static_cast<int>(axis.size()),
      Rcpp::Named("root_degree") = root_degree,
      Rcpp::Named("branch_identity") = "canonical_unrooted_split",
      Rcpp::Named("split_key_schema") =
        "SplitAligner-canonical-split-key-v2"
    )
  );
}

namespace {

struct GeneSplitEvidence {
  bool numeric_available = false;
  double numeric_value = NA_REAL;
  std::string numeric_status = "missing_branch_length";
};

struct GeneDiagnostics {
  int root_lengths = 0;
  int internal_labels = 0;
  int annotations = 0;
  int multifurcations = 0;
  int missing_lengths = 0;
  int failure_markers = 0;
  int negative_lengths = 0;
  int duplicate_split_aliases = 0;
  int fixed_topology_mismatches = 0;
};

struct PrimitiveResult {
  std::string projected_split;
  int side_a_size = 0;
  int side_b_size = 0;
  std::string state;
  std::string reason_code;
  std::string composite_id;
  bool numeric_available = false;
  double numeric_value = NA_REAL;
  std::string numeric_status = "not_applicable";
};

struct CompositeResult {
  std::string coordinate_id;
  std::string projected_split;
  std::vector<int> member_indices;
  std::string recovery_status;
  bool numeric_available = false;
  double numeric_value = NA_REAL;
  std::string numeric_status = "not_applicable";
};

struct OneGeneResult {
  std::string gene_id;
  std::vector<std::string> retained_taxa;
  std::vector<PrimitiveResult> primitive;
  std::vector<CompositeResult> composites;
  GeneDiagnostics diagnostics;
};

struct ParsedGene {
  std::set<std::string> tips;
  std::map<std::string, GeneSplitEvidence> evidence;
  GeneDiagnostics diagnostics;
};

std::vector<std::string> as_string_vector(const Rcpp::List& values,
                                          R_xlen_t index) {
  return Rcpp::as<std::vector<std::string>>(values[index]);
}

std::vector<std::string> restrict_taxa(
    const std::vector<std::string>& taxa,
    const std::set<std::string>& retained) {
  std::vector<std::string> output;
  for (const std::string& taxon : taxa) {
    if (retained.find(taxon) != retained.end()) {
      output.push_back(taxon);
    }
  }
  return output;
}

std::string composite_id_from_members(
    const std::vector<int>& member_indices,
    const std::vector<std::string>& coordinate_ids) {
  std::vector<std::string> members;
  members.reserve(member_indices.size());
  for (int member : member_indices) {
    members.push_back(coordinate_ids[static_cast<std::size_t>(member)]);
  }
  return "F[" + join(members, "|") + "]";
}

std::string retained_taxa_key(const std::vector<std::string>& taxa) {
  std::ostringstream key;
  key << "RT1:" << taxa.size();
  for (const std::string& taxon : taxa) {
    key << ":" << taxon.size() << ":" << taxon;
  }
  return key.str();
}

ParsedGene parse_gene_tree(const std::string& newick,
                           const std::string& gene_id,
                           const std::set<std::string>& species_tips) {
  NewickParser parser(newick);
  const int root_index = parser.parse();
  const std::vector<Node>& nodes = parser.nodes();

  std::vector<int> leaf_nodes;
  collect_leaf_nodes(nodes, root_index, leaf_nodes);
  if (leaf_nodes.size() < 2U) {
    Rcpp::stop("Gene tree `%s` must contain at least two terminal taxa.",
               gene_id.c_str());
  }

  ParsedGene output;
  output.diagnostics.annotations = parser.annotation_count();
  for (int leaf : leaf_nodes) {
    const std::string& label = nodes[leaf].label;
    if (!output.tips.insert(label).second) {
      Rcpp::stop("Gene tree `%s` contains duplicate terminal taxon `%s`.",
                 gene_id.c_str(), label.c_str());
    }
    if (species_tips.find(label) == species_tips.end()) {
      Rcpp::stop(
        "Gene tree `%s` contains taxon `%s`, which is absent from the species tree.",
        gene_id.c_str(), label.c_str()
      );
    }
  }

  std::vector<std::string> all_tips(output.tips.begin(), output.tips.end());
  struct EdgeNumeric {
    bool available = false;
    double value = NA_REAL;
    std::string status;
  };
  std::map<std::string, std::vector<EdgeNumeric>> grouped_edges;

  for (std::size_t node_index = 0; node_index < nodes.size(); ++node_index) {
    const Node& node = nodes[node_index];
    if (!node.children.empty() && !node.label.empty()) {
      ++output.diagnostics.internal_labels;
    }
    const std::size_t graph_degree = node.children.size() +
      (static_cast<int>(node_index) == root_index ? 0U : 1U);
    if (!node.children.empty() && graph_degree > 3U) {
      ++output.diagnostics.multifurcations;
    }
    if (static_cast<int>(node_index) == root_index) {
      if (node.has_length) {
        ++output.diagnostics.root_lengths;
      }
      continue;
    }

    std::vector<std::string> left = descendant_tips(
      nodes, static_cast<int>(node_index)
    );
    const std::set<std::string> left_set(left.begin(), left.end());
    std::vector<std::string> right;
    for (const std::string& tip : all_tips) {
      if (left_set.find(tip) == left_set.end()) {
        right.push_back(tip);
      }
    }
    const CanonicalSplit split = canonical_split(
      std::move(left), std::move(right)
    );

    EdgeNumeric numeric;
    if (!node.has_length) {
      numeric.status = "missing_branch_length";
      ++output.diagnostics.missing_lengths;
    } else {
      const splitaligner::NumericResult checked =
        splitaligner::validate_numeric_token(node.length_token);
      if (checked.accepted) {
        numeric.available = true;
        numeric.value = checked.value;
        numeric.status = "finite_numeric";
        if (checked.is_negative) {
          ++output.diagnostics.negative_lengths;
        }
      } else if (checked.classification == "software_failure_marker" ||
                 checked.classification == "missing") {
        numeric.status = "software_failure_marker";
        ++output.diagnostics.failure_markers;
      } else {
        Rcpp::stop(
          "Gene tree `%s` has rejected branch-length token `%s` (%s): %s.",
          gene_id.c_str(), node.length_token.c_str(),
          checked.classification.c_str(), checked.diagnostic.c_str()
        );
      }
    }
    grouped_edges[split.key].push_back(numeric);
  }

  for (const auto& item : grouped_edges) {
    const std::vector<EdgeNumeric>& edges = item.second;
    output.diagnostics.duplicate_split_aliases +=
      static_cast<int>(edges.size()) - 1;
    GeneSplitEvidence evidence;
    evidence.numeric_available = true;
    evidence.numeric_value = 0.0;
    evidence.numeric_status = "finite_numeric";
    for (const EdgeNumeric& edge : edges) {
      if (!edge.available) {
        evidence.numeric_available = false;
        if (edge.status == "software_failure_marker") {
          evidence.numeric_status = "software_failure_marker";
        } else if (evidence.numeric_status != "software_failure_marker") {
          evidence.numeric_status = "missing_branch_length";
        }
        continue;
      }
      evidence.numeric_value += edge.value;
      if (!std::isfinite(evidence.numeric_value)) {
        Rcpp::stop(
          "Gene tree `%s` has a duplicate-split branch-length sum outside finite double range.",
          gene_id.c_str()
        );
      }
    }
    if (!evidence.numeric_available) {
      evidence.numeric_value = NA_REAL;
    }
    output.evidence[item.first] = evidence;
  }
  return output;
}

Rcpp::DataFrame gene_diagnostic_table(
    const std::vector<OneGeneResult>& genes) {
  static const std::vector<std::string> codes = {
    "IGNORED_GENE_ROOT_LENGTH",
    "IGNORED_INTERNAL_LABEL",
    "IGNORED_ANNOTATION_BLOCK",
    "MULTIFURCATING_GENE_NODE",
    "MISSING_BRANCH_LENGTH",
    "SOFTWARE_FAILURE_MARKER",
    "NEGATIVE_BRANCH_LENGTH",
    "DUPLICATE_GENE_SPLIT_ALIAS",
    "FIXED_TOPOLOGY_MISMATCH"
  };
  static const std::vector<std::string> messages = {
    "Representation-root lengths were parsed and intentionally ignored",
    "Internal labels/support values were parsed and intentionally ignored",
    "Bracket annotation blocks were parsed and intentionally ignored",
    "Gene-tree multifurcations were retained without binary refinement",
    "Recovered topology has branch-length evidence missing on one or more edges",
    "Recognized software failure markers were kept as unavailable numeric evidence",
    "Finite negative values were retained but are outside the nonnegative theorem scope",
    "Equivalent root-representation edges were combined as one unrooted split",
    "A fixed-mode projected coordinate was not recovered by the supplied topology"
  };

  const R_xlen_t row_count = static_cast<R_xlen_t>(
    genes.size() * codes.size()
  );
  Rcpp::CharacterVector gene_id(row_count);
  Rcpp::CharacterVector code(row_count);
  Rcpp::CharacterVector severity(row_count);
  Rcpp::IntegerVector count(row_count);
  Rcpp::CharacterVector message(row_count);
  R_xlen_t row = 0;
  for (const OneGeneResult& gene : genes) {
    const std::vector<int> counts = {
      gene.diagnostics.root_lengths,
      gene.diagnostics.internal_labels,
      gene.diagnostics.annotations,
      gene.diagnostics.multifurcations,
      gene.diagnostics.missing_lengths,
      gene.diagnostics.failure_markers,
      gene.diagnostics.negative_lengths,
      gene.diagnostics.duplicate_split_aliases,
      gene.diagnostics.fixed_topology_mismatches
    };
    for (std::size_t i = 0; i < codes.size(); ++i, ++row) {
      gene_id[row] = gene.gene_id;
      code[row] = codes[i];
      severity[row] = codes[i] == "FIXED_TOPOLOGY_MISMATCH"
        ? "ERROR" : (codes[i] == "NEGATIVE_BRANCH_LENGTH" ? "WARNING" : "INFO");
      count[row] = counts[i];
      message[row] = messages[i];
    }
  }
  return Rcpp::DataFrame::create(
    Rcpp::Named("gene_id") = gene_id,
    Rcpp::Named("code") = code,
    Rcpp::Named("severity") = severity,
    Rcpp::Named("count") = count,
    Rcpp::Named("message") = message,
    Rcpp::Named("stringsAsFactors") = false
  );
}

}  // namespace

// [[Rcpp::export]]
Rcpp::List cpp_align_branches(std::string species_newick,
                              Rcpp::CharacterVector gene_newicks,
                              Rcpp::CharacterVector gene_ids,
                              std::string mode) {
  if (mode != "free" && mode != "fixed") {
    Rcpp::stop("`mode` must be `free` or `fixed`.");
  }
  if (gene_newicks.size() == 0) {
    Rcpp::stop("At least one gene tree is required.");
  }
  if (gene_newicks.size() != gene_ids.size()) {
    Rcpp::stop("Gene-tree text and identifier vectors must have equal length.");
  }

  std::set<std::string> seen_gene_ids;
  for (R_xlen_t i = 0; i < gene_ids.size(); ++i) {
    if (Rcpp::CharacterVector::is_na(gene_ids[i])) {
      Rcpp::stop("Gene identifiers must not be missing.");
    }
    const std::string id = Rcpp::as<std::string>(gene_ids[i]);
    if (id.empty()) {
      Rcpp::stop("Gene identifiers must not be empty.");
    }
    if (!seen_gene_ids.insert(id).second) {
      Rcpp::stop("Duplicate gene identifier `%s`.", id.c_str());
    }
  }

  Rcpp::List species = cpp_validate_species_tree(species_newick);
  const Rcpp::CharacterVector species_tip_vector = species["tip_labels"];
  const std::vector<std::string> species_tip_order =
    Rcpp::as<std::vector<std::string>>(species_tip_vector);
  const std::set<std::string> species_tips(
    species_tip_order.begin(), species_tip_order.end()
  );
  const Rcpp::DataFrame primitive_coordinates =
    Rcpp::as<Rcpp::DataFrame>(species["coordinates"]);
  const Rcpp::CharacterVector coordinate_id_r =
    primitive_coordinates["coordinate_id"];
  const Rcpp::CharacterVector branch_type_r =
    primitive_coordinates["branch_type"];
  const Rcpp::List side_a_r = primitive_coordinates["side_a_taxa"];
  const Rcpp::List side_b_r = primitive_coordinates["side_b_taxa"];
  const std::vector<std::string> coordinate_ids =
    Rcpp::as<std::vector<std::string>>(coordinate_id_r);
  const std::vector<std::string> branch_types =
    Rcpp::as<std::vector<std::string>>(branch_type_r);
  const std::size_t primitive_count = coordinate_ids.size();

  std::vector<std::vector<std::string>> species_side_a(primitive_count);
  std::vector<std::vector<std::string>> species_side_b(primitive_count);
  for (std::size_t i = 0; i < primitive_count; ++i) {
    species_side_a[i] = as_string_vector(side_a_r, static_cast<R_xlen_t>(i));
    species_side_b[i] = as_string_vector(side_b_r, static_cast<R_xlen_t>(i));
  }

  std::vector<OneGeneResult> genes;
  genes.reserve(static_cast<std::size_t>(gene_newicks.size()));
  std::map<std::string, std::vector<int>> composite_definitions;

  for (R_xlen_t gene_index = 0; gene_index < gene_newicks.size(); ++gene_index) {
    if (Rcpp::CharacterVector::is_na(gene_newicks[gene_index])) {
      Rcpp::stop("Gene-tree Newick strings must not be missing.");
    }
    const std::string gene_id = Rcpp::as<std::string>(gene_ids[gene_index]);
    const std::string gene_newick =
      Rcpp::as<std::string>(gene_newicks[gene_index]);
    ParsedGene parsed = parse_gene_tree(gene_newick, gene_id, species_tips);

    OneGeneResult gene;
    gene.gene_id = gene_id;
    gene.retained_taxa.assign(parsed.tips.begin(), parsed.tips.end());
    gene.diagnostics = parsed.diagnostics;
    gene.primitive.resize(primitive_count);

    std::map<std::string, std::vector<int>> projected_groups;
    for (std::size_t i = 0; i < primitive_count; ++i) {
      PrimitiveResult& result = gene.primitive[i];
      const std::vector<std::string> left = restrict_taxa(
        species_side_a[i], parsed.tips
      );
      const std::vector<std::string> right = restrict_taxa(
        species_side_b[i], parsed.tips
      );
      result.side_a_size = static_cast<int>(left.size());
      result.side_b_size = static_cast<int>(right.size());
      if (left.empty() || right.empty()) {
        result.state = "NA_struct";
        result.reason_code = "PROJECTED_SIDE_EMPTY";
        continue;
      }
      const CanonicalSplit split = canonical_split(left, right);
      result.projected_split = split.key;
      projected_groups[split.key].push_back(static_cast<int>(i));
    }

    for (const auto& item : projected_groups) {
      const std::string& projected_key = item.first;
      std::vector<int> members = item.second;
      std::sort(members.begin(), members.end());
      const auto evidence_it = parsed.evidence.find(projected_key);
      const bool recovered = evidence_it != parsed.evidence.end();

      if (members.size() > 1U) {
        const std::string composite_id = composite_id_from_members(
          members, coordinate_ids
        );
        composite_definitions[composite_id] = members;
        CompositeResult composite;
        composite.coordinate_id = composite_id;
        composite.projected_split = projected_key;
        composite.member_indices = members;
        if (!recovered) {
          composite.recovery_status = "unrecovered";
          composite.numeric_status = "not_recovered";
          if (mode == "fixed") {
            ++gene.diagnostics.fixed_topology_mismatches;
          }
        } else {
          const GeneSplitEvidence& evidence = evidence_it->second;
          composite.numeric_available = evidence.numeric_available;
          composite.numeric_value = evidence.numeric_value;
          composite.numeric_status = evidence.numeric_status;
          composite.recovery_status = evidence.numeric_available
            ? "recovered_numeric"
            : "recovered_numeric_unavailable";
        }
        gene.composites.push_back(composite);

        for (int member : members) {
          PrimitiveResult& result =
            gene.primitive[static_cast<std::size_t>(member)];
          result.composite_id = composite_id;
          result.state = "NA_fuse";
          result.reason_code = "COMPOSITE_COORDINATE";
          result.numeric_status = "composite_coordinate_only";
        }
        continue;
      }

      const int member = members.front();
      PrimitiveResult& result =
        gene.primitive[static_cast<std::size_t>(member)];
      const bool eligible = branch_types[static_cast<std::size_t>(member)] ==
          "terminal" ||
        (result.side_a_size >= 2 && result.side_b_size >= 2);
      if (!eligible) {
        Rcpp::stop(
          "Internal invariant failure for gene `%s`, coordinate `%s`: "
          "a nonempty singleton projected side survived without fusion.",
          gene_id.c_str(),
          coordinate_ids[static_cast<std::size_t>(member)].c_str()
        );
      }
      if (!recovered) {
        result.state = "NA_topo";
        result.reason_code = "PROJECTED_SPLIT_NOT_RECOVERED";
        result.numeric_status = "not_recovered";
        if (mode == "fixed") {
          ++gene.diagnostics.fixed_topology_mismatches;
        }
        continue;
      }
      const GeneSplitEvidence& evidence = evidence_it->second;
      result.state = "mapped";
      result.reason_code = "PROJECTED_SPLIT_RECOVERED";
      result.numeric_available = evidence.numeric_available;
      result.numeric_value = evidence.numeric_value;
      result.numeric_status = evidence.numeric_status;
    }
    genes.push_back(std::move(gene));
  }

  std::vector<std::pair<std::string, std::vector<int>>> composites(
    composite_definitions.begin(), composite_definitions.end()
  );
  std::sort(composites.begin(), composites.end(), [](const auto& a,
                                                     const auto& b) {
    return a.second < b.second;
  });
  std::map<std::string, std::size_t> composite_column;
  for (std::size_t i = 0; i < composites.size(); ++i) {
    composite_column[composites[i].first] = primitive_count + i;
  }

  const R_xlen_t gene_count = static_cast<R_xlen_t>(genes.size());
  const R_xlen_t numeric_column_count = static_cast<R_xlen_t>(
    primitive_count + composites.size()
  );
  Rcpp::CharacterMatrix state_matrix(
    gene_count, static_cast<R_xlen_t>(primitive_count)
  );
  Rcpp::NumericMatrix numeric_matrix(gene_count, numeric_column_count);
  std::fill(numeric_matrix.begin(), numeric_matrix.end(), NA_REAL);
  Rcpp::CharacterVector matrix_gene_ids(gene_count);
  Rcpp::CharacterVector state_columns(static_cast<R_xlen_t>(primitive_count));
  Rcpp::CharacterVector numeric_columns(numeric_column_count);
  for (std::size_t i = 0; i < primitive_count; ++i) {
    state_columns[static_cast<R_xlen_t>(i)] = coordinate_ids[i];
    numeric_columns[static_cast<R_xlen_t>(i)] = coordinate_ids[i];
  }
  for (std::size_t i = 0; i < composites.size(); ++i) {
    numeric_columns[static_cast<R_xlen_t>(primitive_count + i)] =
      composites[i].first;
  }

  for (R_xlen_t gene_index = 0; gene_index < gene_count; ++gene_index) {
    const OneGeneResult& gene = genes[static_cast<std::size_t>(gene_index)];
    matrix_gene_ids[gene_index] = gene.gene_id;
    for (std::size_t i = 0; i < primitive_count; ++i) {
      const PrimitiveResult& result = gene.primitive[i];
      state_matrix(gene_index, static_cast<R_xlen_t>(i)) = result.state;
      if (result.numeric_available) {
        numeric_matrix(gene_index, static_cast<R_xlen_t>(i)) =
          result.numeric_value;
      }
    }
    for (const CompositeResult& result : gene.composites) {
      if (result.numeric_available) {
        numeric_matrix(
          gene_index,
          static_cast<R_xlen_t>(composite_column[result.coordinate_id])
        ) = result.numeric_value;
      }
    }
  }
  state_matrix.attr("dimnames") = Rcpp::List::create(
    matrix_gene_ids, state_columns
  );
  numeric_matrix.attr("dimnames") = Rcpp::List::create(
    matrix_gene_ids, numeric_columns
  );

  const R_xlen_t ledger_rows = static_cast<R_xlen_t>(
    genes.size() * primitive_count
  );
  Rcpp::CharacterVector ledger_gene(ledger_rows);
  Rcpp::CharacterVector ledger_coordinate(ledger_rows);
  Rcpp::CharacterVector ledger_split(ledger_rows, NA_STRING);
  Rcpp::IntegerVector ledger_a(ledger_rows);
  Rcpp::IntegerVector ledger_b(ledger_rows);
  Rcpp::CharacterVector ledger_state(ledger_rows);
  Rcpp::CharacterVector ledger_reason(ledger_rows);
  Rcpp::CharacterVector ledger_composite(ledger_rows, NA_STRING);
  Rcpp::LogicalVector ledger_numeric_available(ledger_rows);
  Rcpp::NumericVector ledger_numeric_value(ledger_rows, NA_REAL);
  Rcpp::CharacterVector ledger_numeric_status(ledger_rows);
  R_xlen_t ledger_row = 0;
  for (const OneGeneResult& gene : genes) {
    for (std::size_t i = 0; i < primitive_count; ++i, ++ledger_row) {
      const PrimitiveResult& result = gene.primitive[i];
      ledger_gene[ledger_row] = gene.gene_id;
      ledger_coordinate[ledger_row] = coordinate_ids[i];
      if (!result.projected_split.empty()) {
        ledger_split[ledger_row] = result.projected_split;
      }
      ledger_a[ledger_row] = result.side_a_size;
      ledger_b[ledger_row] = result.side_b_size;
      ledger_state[ledger_row] = result.state;
      ledger_reason[ledger_row] = result.reason_code;
      if (!result.composite_id.empty()) {
        ledger_composite[ledger_row] = result.composite_id;
      }
      ledger_numeric_available[ledger_row] = result.numeric_available;
      if (result.numeric_available) {
        ledger_numeric_value[ledger_row] = result.numeric_value;
      }
      ledger_numeric_status[ledger_row] = result.numeric_status;
    }
  }
  Rcpp::DataFrame state_ledger = Rcpp::DataFrame::create(
    Rcpp::Named("gene_id") = ledger_gene,
    Rcpp::Named("coordinate_id") = ledger_coordinate,
    Rcpp::Named("projected_split") = ledger_split,
    Rcpp::Named("projected_side_a_size") = ledger_a,
    Rcpp::Named("projected_side_b_size") = ledger_b,
    Rcpp::Named("state") = ledger_state,
    Rcpp::Named("reason_code") = ledger_reason,
    Rcpp::Named("composite_id") = ledger_composite,
    Rcpp::Named("numeric_available") = ledger_numeric_available,
    Rcpp::Named("numeric_value") = ledger_numeric_value,
    Rcpp::Named("numeric_status") = ledger_numeric_status,
    Rcpp::Named("stringsAsFactors") = false
  );

  std::size_t composite_ledger_size = 0;
  for (const OneGeneResult& gene : genes) {
    composite_ledger_size += gene.composites.size();
  }
  const R_xlen_t composite_rows = static_cast<R_xlen_t>(
    composite_ledger_size
  );
  Rcpp::CharacterVector composite_gene(composite_rows);
  Rcpp::CharacterVector composite_id(composite_rows);
  Rcpp::CharacterVector composite_split(composite_rows);
  Rcpp::CharacterVector composite_recovery(composite_rows);
  Rcpp::LogicalVector composite_numeric_available(composite_rows);
  Rcpp::NumericVector composite_numeric_value(composite_rows, NA_REAL);
  Rcpp::CharacterVector composite_numeric_status(composite_rows);
  R_xlen_t composite_row = 0;
  for (const OneGeneResult& gene : genes) {
    for (const CompositeResult& result : gene.composites) {
      composite_gene[composite_row] = gene.gene_id;
      composite_id[composite_row] = result.coordinate_id;
      composite_split[composite_row] = result.projected_split;
      composite_recovery[composite_row] = result.recovery_status;
      composite_numeric_available[composite_row] = result.numeric_available;
      if (result.numeric_available) {
        composite_numeric_value[composite_row] = result.numeric_value;
      }
      composite_numeric_status[composite_row] = result.numeric_status;
      ++composite_row;
    }
  }
  Rcpp::DataFrame composite_ledger = Rcpp::DataFrame::create(
    Rcpp::Named("gene_id") = composite_gene,
    Rcpp::Named("composite_id") = composite_id,
    Rcpp::Named("projected_split") = composite_split,
    Rcpp::Named("recovery_status") = composite_recovery,
    Rcpp::Named("numeric_available") = composite_numeric_available,
    Rcpp::Named("numeric_value") = composite_numeric_value,
    Rcpp::Named("numeric_status") = composite_numeric_status,
    Rcpp::Named("stringsAsFactors") = false
  );

  const R_xlen_t definition_rows = static_cast<R_xlen_t>(composites.size());
  Rcpp::CharacterVector definition_id(definition_rows);
  Rcpp::IntegerVector definition_count(definition_rows);
  Rcpp::CharacterVector definition_text(definition_rows);
  Rcpp::List definition_members(definition_rows);
  for (R_xlen_t i = 0; i < definition_rows; ++i) {
    const auto& definition = composites[static_cast<std::size_t>(i)];
    std::vector<std::string> members;
    for (int member : definition.second) {
      members.push_back(coordinate_ids[static_cast<std::size_t>(member)]);
    }
    definition_id[i] = definition.first;
    definition_count[i] = static_cast<int>(members.size());
    definition_text[i] = join(members, "|");
    definition_members[i] = Rcpp::wrap(members);
  }
  definition_members.attr("class") = "AsIs";
  Rcpp::DataFrame composite_coordinates = Rcpp::DataFrame::create(
    Rcpp::Named("coordinate_id") = definition_id,
    Rcpp::Named("coordinate_type") = Rcpp::CharacterVector(
      definition_rows, "composite"
    ),
    Rcpp::Named("member_count") = definition_count,
    Rcpp::Named("member_text") = definition_text,
    Rcpp::Named("primitive_members") = definition_members,
    Rcpp::Named("stringsAsFactors") = false
  );

  Rcpp::CharacterVector provenance_gene(gene_count);
  Rcpp::IntegerVector provenance_count(gene_count);
  Rcpp::CharacterVector provenance_key(gene_count);
  Rcpp::List provenance_taxa(gene_count);
  for (R_xlen_t i = 0; i < gene_count; ++i) {
    const OneGeneResult& gene = genes[static_cast<std::size_t>(i)];
    provenance_gene[i] = gene.gene_id;
    provenance_count[i] = static_cast<int>(gene.retained_taxa.size());
    provenance_key[i] = retained_taxa_key(gene.retained_taxa);
    provenance_taxa[i] = Rcpp::wrap(gene.retained_taxa);
  }
  provenance_taxa.attr("class") = "AsIs";
  Rcpp::DataFrame gene_provenance = Rcpp::DataFrame::create(
    Rcpp::Named("gene_id") = provenance_gene,
    Rcpp::Named("retained_taxon_count") = provenance_count,
    Rcpp::Named("retained_taxa_key") = provenance_key,
    Rcpp::Named("retained_taxa") = provenance_taxa,
    Rcpp::Named("stringsAsFactors") = false
  );

  return Rcpp::List::create(
    Rcpp::Named("state_matrix") = state_matrix,
    Rcpp::Named("numeric_matrix") = numeric_matrix,
    Rcpp::Named("state_ledger") = state_ledger,
    Rcpp::Named("primitive_coordinates") = primitive_coordinates,
    Rcpp::Named("composite_coordinates") = composite_coordinates,
    Rcpp::Named("composite_ledger") = composite_ledger,
    Rcpp::Named("gene_provenance") = gene_provenance,
    Rcpp::Named("diagnostics") = gene_diagnostic_table(genes),
    Rcpp::Named("species_tree") = species,
    Rcpp::Named("conventions") = Rcpp::List::create(
      Rcpp::Named("branch_identity") = "canonical_unrooted_split",
      Rcpp::Named("root_treatment") = "representation_only",
      Rcpp::Named("degree2_policy") = "suppress_by_projected_edge_grouping",
      Rcpp::Named("multifurcation_policy") = "retain_actual_edges_only",
      Rcpp::Named("terminal_policy") =
        "retained_terminal_split_never_NA_topo",
      Rcpp::Named("state_numeric_independence") = true,
      Rcpp::Named("numeric_policy") = "finite-double-v1",
      Rcpp::Named("ordering") = "deterministic_B_then_member_order",
      Rcpp::Named("retained_taxa_key_schema") =
        "length-prefixed-UTF8-bytes-RT1"
    ),
    Rcpp::Named("metadata") = Rcpp::List::create(
      Rcpp::Named("core_version") = "0.1.0",
      Rcpp::Named("schema_version") = "1.0.0",
      Rcpp::Named("mode") = mode,
      Rcpp::Named("gene_count") = static_cast<int>(genes.size()),
      Rcpp::Named("primitive_coordinate_count") =
        static_cast<int>(primitive_count),
      Rcpp::Named("composite_coordinate_count") =
        static_cast<int>(composites.size()),
      Rcpp::Named("state_schema") = "single-tree-state-v1",
      Rcpp::Named("numeric_policy") = "finite-double-v1",
      Rcpp::Named("split_key_schema") =
        "SplitAligner-canonical-split-key-v2",
      Rcpp::Named("retained_taxa_key_schema") =
        "length-prefixed-UTF8-bytes-RT1",
      Rcpp::Named("production_core") = "C++17 graph-first mapper"
    )
  );
}
