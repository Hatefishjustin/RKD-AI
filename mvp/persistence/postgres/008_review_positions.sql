CREATE TABLE rkd.review_position (
 organization_id text NOT NULL REFERENCES rkd.organization(organization_id), position_key text NOT NULL,
 name text NOT NULL, active boolean NOT NULL, version integer NOT NULL,
 PRIMARY KEY(organization_id,position_key)
);
CREATE TABLE rkd.review_position_member (
 organization_id text NOT NULL, position_key text NOT NULL, user_id text NOT NULL REFERENCES rkd.auth_user(user_id),
 PRIMARY KEY(organization_id,position_key,user_id),
 FOREIGN KEY(organization_id,position_key) REFERENCES rkd.review_position(organization_id,position_key)
);
ALTER TABLE rkd.review_position ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.review_position_member ENABLE ROW LEVEL SECURITY;
CREATE POLICY review_position_scope ON rkd.review_position USING (organization_id=rkd.current_organization()) WITH CHECK (organization_id=rkd.current_organization());
CREATE POLICY review_position_member_scope ON rkd.review_position_member USING (organization_id=rkd.current_organization()) WITH CHECK (organization_id=rkd.current_organization());
