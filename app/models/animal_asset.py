from app.extensions import db
from app.models.base import JSONType, new_uuid, utcnow

SPECIES = ("dog", "cat", "other")
LICENSE_STATUSES = ("pending", "approved", "rejected")
# memory: solo tablero de parejas; breed: solo preguntas de raza; both: cualquiera de los dos.
USAGES = ("memory", "breed", "both")


class AnimalAsset(db.Model):
    __tablename__ = "animal_assets"
    __table_args__ = (db.Index("ix_animal_assets_species_active_license", "species", "active", "license_status"),)

    id = db.Column(db.Uuid, primary_key=True, default=new_uuid)
    species = db.Column(db.String(20), nullable=False)
    usage = db.Column(db.String(20), nullable=False, default="both")
    breed_external_id = db.Column(db.String(100), nullable=True)
    breed_name_es = db.Column(db.String(100), nullable=True)
    provider = db.Column(db.String(50), nullable=False)
    source_url = db.Column(db.Text, nullable=False)
    local_path = db.Column(db.Text, nullable=False)
    license_status = db.Column(db.String(30), nullable=False, default="pending")
    attribution = db.Column(db.Text, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=False)
    metadata_json = db.Column("metadata", JSONType, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    @property
    def usable_for_memory(self) -> bool:
        return self.usage in ("memory", "both")

    @property
    def usable_for_breed(self) -> bool:
        return self.usage in ("breed", "both") and self.species in ("dog", "cat") and bool(self.breed_name_es)

    @property
    def is_playable(self) -> bool:
        return self.active and self.license_status == "approved"
