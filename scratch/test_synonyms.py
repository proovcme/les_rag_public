from proxy.services.kot_service import expand_query_synonyms

question = "Нужно ли тушить серверную газом и от какой площади?"
expanded = expand_query_synonyms(question)
print("Original:", repr(question))
print("Expanded:", repr(expanded))
