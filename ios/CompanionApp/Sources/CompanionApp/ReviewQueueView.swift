import SwiftUI

struct ReviewItem: Identifiable {
    let id: String
    let title: String
    let snippet: String
}

struct ReviewQueueView: View {
    @State private var items: [ReviewItem] = [
        ReviewItem(id: "e1", title: "Buy milk", snippet: "Remember to buy milk on way home"),
        ReviewItem(id: "e2", title: "Call Alice", snippet: "Confirm meeting time")
    ]

    var body: some View {
        NavigationView {
            List {
                ForEach(items) { item in
                    VStack(alignment: .leading) {
                        Text(item.title).font(.headline)
                        Text(item.snippet).font(.subheadline).foregroundColor(.secondary)
                        HStack {
                            Button("Tag") { /* stub */ }
                            Spacer()
                            Button("Archive") { archive(id: item.id) }
                        }
                        .padding(.top, 8)
                    }
                    .padding(.vertical, 8)
                }
            }
            .navigationTitle("Review Queue")
        }
    }

    private func archive(id: String) {
        items.removeAll { $0.id == id }
    }
}

#if DEBUG
struct ReviewQueueView_Previews: PreviewProvider {
    static var previews: some View {
        ReviewQueueView()
    }
}
#endif
