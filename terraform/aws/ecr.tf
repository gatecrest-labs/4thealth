resource "aws_ecr_repository" "app" {
  name                 = var.cluster_name
  image_tag_mutability = "IMMUTABLE" # forces real tags (git SHA/semver), never :latest

  image_scanning_configuration {
    scan_on_push = true
  }
}
