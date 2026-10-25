package domain

// DiscoveredAssignment is independent from the fixed forecast compatibility enum.
// Similarity is a relation cosine, never a correctness probability.
type DiscoveredAssignment struct {
	Status              string   `json:"status"`
	CategoryID          string   `json:"category_id,omitempty"`
	CategoryTitle       string   `json:"category_title,omitempty"`
	CoarseCategoryID    string   `json:"coarse_category_id,omitempty"`
	CoarseCategoryTitle string   `json:"coarse_category_title,omitempty"`
	CategoryPath        []string `json:"category_path"`
	TaxonomyVersion     string   `json:"taxonomy_version,omitempty"`
	EncoderVersion      string   `json:"encoder_version,omitempty"`
	ScoreKind           string   `json:"score_kind,omitempty"`
	Similarity          *float64 `json:"similarity,omitempty"`
	ForecastCategory    Category `json:"forecast_category"`
	ProjectionVersion   string   `json:"projection_version,omitempty"`
	ProjectionSource    string   `json:"projection_source,omitempty"`
}
